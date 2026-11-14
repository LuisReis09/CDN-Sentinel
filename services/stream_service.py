from __future__ import annotations

import time
import uuid
import requests

from models.entities import Client, SimulationState, VideoChunk
from services.cdn_http_client import CDNHttpClient
from services.content_provider import default_content_id
from utils.geo import haversine_km, rank_delivery_servers
from utils.latency import sleep_for_distance


class SimulationPausedError(RuntimeError):
    """Raised when streaming is requested while the simulation is paused."""


class StreamService:
    def __init__(self, http_client: CDNHttpClient, repository=None, watermark_service=None) -> None:
        self._http_client = http_client
        self._repository = repository
        self._watermark_service = watermark_service

    def record_delivery_feedback(self, client: Client, watch_record: dict, source: str = "client_process") -> dict:
        """Let the simulated client rate a delivered service automatically.

        Feedback is derived from the observed end-to-end delivery time. The
        browser only reads this history; it is never the actor that submits it.
        """
        latency_ms = float(watch_record.get("latency_ms", 0.0))
        if latency_ms <= 120:
            rating = 5
        elif latency_ms <= 250:
            rating = 4
        elif latency_ms <= 450:
            rating = 3
        elif latency_ms <= 700:
            rating = 2
        else:
            rating = 1
        liked = rating >= 4
        feedback = {
            "at": time.time(),
            "video_id": watch_record.get("video_id") or "unknown",
            "chunk_number": watch_record.get("chunk_number"),
            "liked": liked,
            "rating": rating,
            "comment": "feedback automático do processo cliente",
            "latency_ms": round(latency_ms, 3),
            "latency_related": latency_ms >= 250.0,
            "source": source,
            "automatic": True,
        }
        client.feedback_history.append(feedback)
        client.feedback_history = client.feedback_history[-100:]
        client.likes += int(liked)
        client.dislikes += int(not liked)
        client.feedback_score = round(
            sum(item["rating"] for item in client.feedback_history)
            / len(client.feedback_history)
            * 20.0,
            2,
        )
        client.feedback_latency_avg_ms = round(
            sum(float(item.get("latency_ms", 0.0)) for item in client.feedback_history)
            / len(client.feedback_history),
            3,
        )
        watch_record["liked"] = liked
        if self._repository:
            self._repository.append_event({
                "type": "client_feedback_generated",
                "at": feedback["at"],
                "client_id": client.client_id,
                "server_id": watch_record.get("server_id"),
                "video_id": feedback["video_id"],
                "liked": liked,
                "rating": rating,
                "latency_ms": feedback["latency_ms"],
                "source": source,
            })
        return feedback

    def stream(self, client: Client, state: SimulationState, chunk_number: int = 0, request_id: str | None = None, *, viewer_session_id: str | None = None, forensic_capture: bool = False) -> VideoChunk:
        if state.paused:
            raise SimulationPausedError("A simulação está pausada")
        temporary_entry = state.temporary_blacklist.get(client.client_id)
        if not forensic_capture and temporary_entry and float(temporary_entry.get("expires_at", 0)) > time.time():
            raise PermissionError("cliente temporariamente bloqueado durante a analise forense")
        if not forensic_capture and client.client_id in state.forensic_pending_clients:
            raise PermissionError("cliente temporariamente bloqueado durante a analise forense")
        if chunk_number < 0:
            raise ValueError("chunk deve ser maior ou igual a zero")
        request_id = request_id or f"req-{uuid.uuid4().hex[:16]}"
        trace_id = f"trace-{uuid.uuid4().hex[:16]}"
        candidates = rank_delivery_servers(
            client.latitude, client.longitude, state.servers.values()
        )
        if not candidates:
            raise RuntimeError("Nenhum servidor CDN saudável está disponível")
        candidate_details = [
            {
                "server_id": server.server_id,
                "routing_score": round(score, 2),
                "distance_km": round(
                    haversine_km(
                        client.latitude, client.longitude, server.latitude, server.longitude
                    ),
                    2,
                ),
                "status": server.status,
                "selected": False,
                "attempted": False,
                "reason": "eligible by distance and load",
            }
            for score, server in candidates
        ]
        healthy_ids = {server.server_id for _, server in candidates}
        for server in state.servers.values():
            if server.server_id not in healthy_ids:
                candidate_details.append({"server_id": server.server_id, "distance_km": round(haversine_km(client.latitude, client.longitude, server.latitude, server.longitude), 2), "status": server.status, "selected": False, "attempted": False, "reason": "excluído: nó não saudável"})
        started = time.monotonic()
        result = None
        selected_server = None
        selected_distance = 0.0
        failures: list[str] = []
        blocked_failures: list[str] = []
        for index, (_score, candidate) in enumerate(candidates):
            distance = haversine_km(
                client.latitude, client.longitude, candidate.latitude, candidate.longitude
            )
            candidate_details[index]["selected"] = True
            candidate_details[index]["attempted"] = True
            try:
                stream_args = (candidate, client.client_id, chunk_number, distance, float(state.config["latency_factor"]), str(state.config.get("video_id") or default_content_id()))
                stream_kwargs = {"forensic_capture": True} if forensic_capture else {}
                if viewer_session_id:
                    stream_kwargs["viewer_session_id"] = viewer_session_id
                result = self._http_client.stream(*stream_args, **stream_kwargs)
                if self._watermark_service and result.get("watermark_token"):
                    self._watermark_service.register_token(str(result["watermark_token"]))
                selected_server = candidate
                selected_distance = distance
                candidate_details[index]["reason"] = "selecionado; resposta HTTP válida"
                break
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code == 403:
                    blocked_failures.append(candidate.server_id)
                    failures.append(f"{candidate.server_id}: blacklist local")
                    candidate_details[index]["selected"] = False
                    candidate_details[index]["reason"] = "blacklist local; tentando o próximo nó durante a propagação"
                    continue
                if status_code == 429:
                    failures.append(f"{candidate.server_id}: capacidade saturada")
                    candidate_details[index]["selected"] = False
                    candidate_details[index]["reason"] = "fila cheia; failover para o próximo candidato"
                    continue
                failures.append(f"{candidate.server_id}: HTTP {status_code or 'erro'}")
                candidate.status = "offline"
                candidate.last_error = "falha HTTP durante roteamento"
                candidate_details[index]["selected"] = False
                candidate_details[index]["reason"] = "falha HTTP; failover para o próximo candidato"
            except requests.RequestException as exc:
                failures.append(f"{candidate.server_id}: {exc.__class__.__name__}")
                candidate.status = "offline"
                candidate.last_error = "falha HTTP durante roteamento"
                candidate_details[index]["selected"] = False
                candidate_details[index]["reason"] = "falha HTTP; failover para o próximo candidato"
        if result is None or selected_server is None:
            if blocked_failures and len(blocked_failures) == len(candidates):
                raise PermissionError(f"Cliente {client.client_id} foi rejeitado pela blacklist local em todos os nós: {', '.join(blocked_failures)}")
            raise RuntimeError("Todos os nós candidatos falharam: " + "; ".join(failures))
        server = selected_server
        distance = selected_distance
        routing_reason = "primeiro nó falhou; failover determinístico" if failures else ("nó não saudável excluído; menor custo de distância e carga" if len(candidate_details) > len(candidates) else "menor custo de distância e carga entre nós saudáveis")
        server.load = int(result.get("load", server.load))
        if not forensic_capture:
            client.videos_consumed += 1
            client.last_activity_at = time.time()
        artificial_latency_ms = float(result.get("network_latency_ms", 0.0))
        http_rtt_ms = float(result.get("http_rtt_ms", 0.0))
        queue_wait_ms = float(result.get("queue_wait_ms", 0.0))
        end_to_end_ms = (time.monotonic() - started) * 1000
        watch_record = {
            "at": time.time(),
            "video_id": state.config.get("video_id") or default_content_id(),
            "chunk_number": chunk_number,
            "chunk_id": result["chunk_id"],
            "server_id": server.server_id,
            "latency_ms": round(end_to_end_ms, 3),
            "network_latency_ms": round(artificial_latency_ms, 3),
            "queue_wait_ms": round(queue_wait_ms, 3),
            "liked": None,
            "watermark_version": result.get("watermark_version", "CDNWM4"),
            "watermark_algorithm": result.get("watermark_algorithm", "dct-qim-v3"),
            "watermark_id": result.get("watermark_id"),
        }
        if not forensic_capture:
            client.watch_history.append(watch_record)
            client.watch_history = client.watch_history[-100:]
            self.record_delivery_feedback(client, watch_record)
        if self._repository:
            self._repository.append_traffic({
                "at": time.time(),
                "request_id": request_id,
                "trace_id": trace_id,
                "client_id": client.client_id,
                "server_id": server.server_id,
                "distance_km": round(distance, 2),
                "latency_ms": artificial_latency_ms,
                "artificial_latency_ms": artificial_latency_ms,
                "http_rtt_ms": http_rtt_ms,
                "queue_wait_ms": queue_wait_ms,
                "end_to_end_ms": round(end_to_end_ms, 3),
                "chunk_id": result["chunk_id"],
                "routing_reason": routing_reason,
                "route_kind": "failover" if failures else "delivery",
                "forensic_capture": forensic_capture,
            })
            self._repository.append_event({
                "type": "forensic_capture" if forensic_capture else "client_request",
                "at": time.time(),
                "request_id": request_id,
                "trace_id": trace_id,
                "client_id": client.client_id,
                "server_id": server.server_id,
                "latency_ms": artificial_latency_ms,
                "artificial_latency_ms": artificial_latency_ms,
                "http_rtt_ms": http_rtt_ms,
                "queue_wait_ms": queue_wait_ms,
                "end_to_end_ms": round(end_to_end_ms, 3),
                "protocol": "HTTP/1.1",
                "routing": "Haversine + balanceamento por pressão",
                "watermark_algorithm": result.get("watermark_algorithm", "dct-qim-v3"),
                "watermark_version": result.get("watermark_version", "CDNWM4"),
                "watermark_id": result.get("watermark_id"),
                "chunk_id": result["chunk_id"],
                "content_id": state.config.get("video_id") or default_content_id(),
                "content_title": state.config.get("video_id") or default_content_id(),
                "routing_candidates": candidate_details,
                "routing_reason": routing_reason,
                "forensic_capture": forensic_capture,
            })
            if failures:
                self._repository.append_event({
                    "type": "server_message",
                    "at": time.time(),
                    "message_id": f"failover-{request_id}",
                    "message_type": "FAILOVER_ROUTE",
                    "communication_kind": "failover",
                    "from_server": failures[0].split(":", 1)[0],
                    "to_server": server.server_id,
                    "client_id": client.client_id,
                    "status": "acknowledged",
                    "payload_summary": "requisição desviada após falha do primeiro candidato",
                    "protocol": "HTTP/1.1 failover",
                    "trace_id": trace_id,
                })
            peer_ids = set(server.peer_ids)
            peers = [
                peer
                for peer in state.servers.values()
                if peer.server_id != server.server_id
                and peer.server_id in peer_ids
                and peer.process_mode == "http"
                and peer.status in {"healthy", "degraded", "overloaded"}
            ]
            if peers and client.videos_consumed % 3 == 0:
                peer = peers[client.videos_consumed % len(peers)]
                message = {
                    "message_id": f"content-{uuid.uuid4().hex[:10]}",
                    "message_type": "CONTENT_PLAYBACK_TELEMETRY",
                    "communication_kind": "update",
                    "content_id": state.config.get("video_id") or default_content_id(),
                    "content_title": state.config.get("video_id") or default_content_id(),
                    "chunk_id": result["chunk_id"],
                    "region": server.city,
                    "viewer_count_delta": 1,
                    "from_server": server.server_id,
                    "to_server": peer.server_id,
                    "encryption": "AES-256-GCM",
                    "session_event": "playback_chunk",
                    "sent_at": time.time(),
                }
                try:
                    ack = self._http_client.publish_content_telemetry(peer, message)
                    self._repository.append_event({"type": "server_message", "at": time.time(), **message, "status": "acknowledged", "payload_summary": "content_id + chunk + região + viewer_count_delta", "ack_server_id": ack.get("server_id"), "encryption": ack.get("encryption", "AES-256-GCM")})
                except Exception as exc:
                    self._repository.append_event({"type": "server_message", "at": time.time(), **message, "status": "failed", "payload_summary": "content_id + chunk + região + viewer_count_delta", "error": str(exc)})
        return VideoChunk(
            chunk_id=result["chunk_id"],
            content_type=result["content_type"],
            payload=result["payload"],
            watermark_token=result["watermark_token"],
            server_id=result["server_id"],
            client_id=client.client_id,
            issued_at=float(result["issued_at"]),
            latency_ms=artificial_latency_ms,
            request_id=request_id,
            trace_id=trace_id,
            artificial_latency_ms=artificial_latency_ms,
            http_rtt_ms=http_rtt_ms,
            queue_wait_ms=queue_wait_ms,
            end_to_end_ms=round(end_to_end_ms, 3),
            routing_candidates=candidate_details,
            routing_reason=routing_reason,
        )

    def publish_server_message(self, source_server, target_server, message: dict, latency_factor: float) -> dict:
        """Send a cross-region control/content message over the node HTTP API."""
        distance = haversine_km(source_server.latitude, source_server.longitude, target_server.latitude, target_server.longitude)
        sleep_for_distance(distance, latency_factor)
        return self._http_client.publish_content_telemetry(target_server, message)

