from __future__ import annotations

import time
import uuid
import requests

from models.entities import Client, SimulationState, VideoChunk
from services.cdn_http_client import CDNHttpClient
from utils.geo import haversine_km, rank_servers
from utils.latency import sleep_for_distance


class SimulationPausedError(RuntimeError):
    """Raised when streaming is requested while the simulation is paused."""


class ClientOfflineError(RuntimeError):
    """Raised when a disconnected simulated client requests a stream."""


class StreamService:
    def __init__(self, http_client: CDNHttpClient, repository=None) -> None:
        self._http_client = http_client
        self._repository = repository

    def stream(self, client: Client, state: SimulationState, chunk_number: int = 0, request_id: str | None = None) -> VideoChunk:
        if state.paused:
            raise SimulationPausedError("A simulação está pausada")
        if not client.online:
            raise ClientOfflineError(f"Cliente {client.client_id} está offline")
        if chunk_number < 0:
            raise ValueError("chunk deve ser maior ou igual a zero")
        request_id = request_id or f"req-{uuid.uuid4().hex[:16]}"
        trace_id = f"trace-{uuid.uuid4().hex[:16]}"
        candidates = rank_servers(client.latitude, client.longitude, state.servers.values())
        policy = str(state.config.get("load_balancing_policy", "nearest-healthy"))
        if policy == "least-utilized":
            candidates.sort(key=lambda item: (float(getattr(item[1], "utilization", 0.0)), item[0], item[1].server_id))
        elif policy == "hybrid-latency-capacity":
            candidates.sort(key=lambda item: (0.65 * min(1.0, float(getattr(item[1], "utilization", 0.0))) + 0.35 * min(1.0, item[0] / 20_000.0), item[1].server_id))
        if not candidates:
            raise RuntimeError("Nenhum servidor CDN saudável está disponível")
        candidate_details = [{"server_id": server.server_id, "distance_km": round(distance, 2), "status": server.status, "selected": False, "attempted": False, "reason": "candidato saudável"} for distance, server in candidates]
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
        for index, (distance, candidate) in enumerate(candidates):
            candidate_details[index]["selected"] = True
            candidate_details[index]["attempted"] = True
            try:
                result = self._http_client.stream(candidate, client.client_id, chunk_number, distance, float(state.config["latency_factor"]), str(state.config.get("video_id", "bigbuckbunny")))
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
        server.load = int(result.get("load", server.load))
        client.videos_consumed += 1
        client.last_activity_at = time.time()
        artificial_latency_ms = float(result.get("network_latency_ms", 0.0))
        http_rtt_ms = float(result.get("http_rtt_ms", 0.0))
        queue_wait_ms = float(result.get("queue_wait_ms", 0.0))
        end_to_end_ms = (time.monotonic() - started) * 1000
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
            })
            self._repository.append_event({
                "type": "client_request",
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
                "routing": policy,
                "watermark_algorithm": "HMAC-SHA256",
                "chunk_id": result["chunk_id"],
                "content_id": state.config.get("video_id", "bigbuckbunny"),
                "content_title": state.config.get("video_id", "bigbuckbunny"),
                "routing_candidates": candidate_details,
                "routing_reason": "primeiro nó falhou; failover determinístico" if failures else ("nó não saudável excluído; menor distância entre nós saudáveis" if len(candidate_details) > len(candidates) else "menor distância entre nós saudáveis"),
            })
            peers = [peer for peer in state.servers.values() if peer.server_id != server.server_id and peer.status == "healthy"]
            if peers and client.videos_consumed % 3 == 0:
                peer = peers[client.videos_consumed % len(peers)]
                message = {
                    "message_id": f"content-{uuid.uuid4().hex[:10]}",
                    "message_type": "CONTENT_PLAYBACK_TELEMETRY",
                    "communication_kind": "update",
                    "content_id": state.config.get("video_id", "bigbuckbunny"),
                    "content_title": state.config.get("video_id", "bigbuckbunny"),
                    "chunk_id": result["chunk_id"],
                    "region": server.city,
                    "viewer_count_delta": 1,
                    "from_server": server.server_id,
                    "to_server": peer.server_id,
                    "session_event": "playback_chunk",
                    "sent_at": time.time(),
                }
                try:
                    ack = self._http_client.publish_content_telemetry(peer, message)
                    self._repository.append_event({"type": "server_message", "at": time.time(), **message, "status": "acknowledged", "payload_summary": "content_id + chunk + região + viewer_count_delta", "ack_server_id": ack.get("server_id")})
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
            routing_reason="primeiro nó falhou; failover determinístico" if failures else ("nó não saudável excluído; menor distância entre nós saudáveis" if len(candidate_details) > len(candidates) else "menor distância entre nós saudáveis"),
        )

    def publish_server_message(self, source_server, target_server, message: dict, latency_factor: float) -> dict:
        """Send a cross-region control/content message over the node HTTP API."""
        distance = haversine_km(source_server.latitude, source_server.longitude, target_server.latitude, target_server.longitude)
        sleep_for_distance(distance, latency_factor)
        return self._http_client.publish_content_telemetry(target_server, message)

