from __future__ import annotations

import argparse
import base64
import hashlib
import os
import random
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from flask import Flask, Response, jsonify, request

from repositories.in_memory import NodeRepository
from services.capacity_service import profile_for_tier, service_metrics, queue_wait_ms
from services.content_provider import ContentProvider, DatasetContentProvider, HybridContentProvider, DATASET_CONTENT_ID, default_content_id
from services.watermark_service import WatermarkService
from utils.geo import haversine_km
from utils.latency import sleep_for_distance
from utils.crypto import decrypt_payload, encrypt_payload, is_encrypted_payload
from utils.video import encode_payload
from utils.protocol import signed_headers, verify_headers
from utils.video_watermark import VIDEO_STRENGTH, embed_video, probe_video_limits
from utils.qim_watermark import QIM_STEP


class CapacityRejected(RuntimeError):
    """Raised when the bounded node queue cannot admit another request."""


class CDNNode:
    """State and HTTP handlers for one independent CDN process."""

    def __init__(self, server_id: str, host: str, port: int, latitude: float, longitude: float, city: str, secret_key: str, latency_factor: float, capacity_tier: str = "basic", content_provider: ContentProvider | None = None) -> None:
        self.server_id = server_id
        self.host = host
        self.port = port
        self.latitude = latitude
        self.longitude = longitude
        self.city = city
        self.latency_factor = latency_factor
        self.capacity_tier = capacity_tier
        self.capacity_profile = profile_for_tier(capacity_tier)
        self.repository = NodeRepository()
        self.watermark_service = WatermarkService(secret_key)
        self.content_provider = content_provider or HybridContentProvider()
        self.secret_key = secret_key
        self.peers: list[dict] = []
        self._lock = threading.RLock()
        self.started_at = time.time()
        self.fault = {"offline": False, "extra_latency_ms": 0.0, "drop_rate": 0.0}
        self._retry_stop = threading.Event()
        self._retry_thread = threading.Thread(target=self._retry_pending, name=f"gossip-retry-{server_id}", daemon=True)
        self._retry_thread.start()

    def configure_peers(self, peers: list[dict]) -> None:
        with self._lock:
            self.peers = [peer for peer in peers if peer["server_id"] != self.server_id]

    def configure(self, values: dict) -> dict:
        with self._lock:
            if "latency_factor" in values:
                self.latency_factor = float(values["latency_factor"])
            if "capacity_tier" in values:
                self.capacity_tier = str(values["capacity_tier"])
                self.capacity_profile = profile_for_tier(self.capacity_tier)
            if "fault" in values:
                fault = values["fault"] or {}
                if not isinstance(fault, dict):
                    raise ValueError("fault deve ser um objeto")
                self.fault["offline"] = bool(fault.get("offline", self.fault["offline"]))
                self.fault["extra_latency_ms"] = max(0.0, min(30_000.0, float(fault.get("extra_latency_ms", self.fault["extra_latency_ms"]))))
                self.fault["drop_rate"] = max(0.0, min(1.0, float(fault.get("drop_rate", self.fault["drop_rate"]))))
                if not self.fault["offline"] and not self.fault["extra_latency_ms"] and not self.fault["drop_rate"]:
                    self.repository.clear_consecutive_errors()
        return {"server_id": self.server_id, "latency_factor": self.latency_factor, "capacity_tier": self.capacity_tier, "capacity_profile": self.capacity_profile.to_dict(), "fault": dict(self.fault)}

    def _post_peer(self, peer: dict, path: str, payload: dict) -> dict:
        """Send an authenticated, encrypted hop to a neighbouring CDN node."""

        url = f"{peer['url']}{path}"
        wire_payload = encrypt_payload(payload, self.secret_key, aad=path)
        response = requests.post(
            url,
            json=wire_payload,
            headers=signed_headers(self.secret_key, "POST", path, wire_payload),
            timeout=2.0,
        )
        response.raise_for_status()
        return response.json()

    def status(self) -> dict:
        metrics = self.repository.request_metrics()
        capacity = service_metrics(
            self.capacity_profile,
            metrics.get("observed_rps", 0.0),
            metrics.get("queue_depth", 0),
            metrics.get("queue_rejected", 0),
        )
        pressure = capacity["pressure"]
        is_overloaded = pressure >= 0.9
        is_degraded = bool(self.fault["extra_latency_ms"] or self.fault["drop_rate"] or metrics.get("consecutive_errors"))
        health_status = "offline" if self.fault["offline"] else ("overloaded" if is_overloaded else ("degraded" if is_degraded else "healthy"))
        return {
            "server_id": self.server_id,
            "host": self.host,
            "port": self.port,
            "city": self.city,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "status": health_status,
            "lifecycle_status": "failed" if self.fault["offline"] else "running",
            "health_status": health_status,
            "capacity_tier": self.capacity_tier,
            "capacity_profile": self.capacity_profile.to_dict(),
            "capacity": capacity,
            "load": self.repository.load(),
            "blacklist_size": len(self.repository.blacklist()),
            "messages_received": self.repository.message_count(),
            "peers": [peer["server_id"] for peer in self.peers],
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "fault": dict(self.fault),
            **metrics,
        }

    def _watermarked_media(self, video_id: str, chunk_number: int, token: str, content: bytes, content_type: str, algorithm: str = "adaptive-spread") -> bytes:
        """Return a playable media payload with the visual marker in its frames.

        The token is deliberately kept as response metadata. It is never
        prepended to the MP4 bytes, because that would corrupt the container
        and would not constitute a visual watermark. A disk cache prevents
        concurrent/repeated requests from re-encoding the same asset.
        """
        if not content_type.startswith("video/"):
            return content
        resolver = getattr(self.content_provider, "resolve_asset", None)
        source_path: Path | None = None
        if resolver is not None:
            try:
                source_path, _resolved_type = resolver(video_id, chunk_number)
            except (FileNotFoundError, KeyError, ValueError, OSError):
                source_path = None
        temporary_source: Path | None = None
        try:
            if source_path is None or not source_path.is_file():
                runtime_root = Path(os.getenv("CDN_WATERMARK_CACHE_ROOT", "data/runtime/watermarked"))
                runtime_root.mkdir(parents=True, exist_ok=True)
                temporary_source = runtime_root / f"source-{hashlib.sha256(content).hexdigest()[:24]}.mp4"
                if not temporary_source.exists():
                    temporary_source.write_bytes(content)
                source_path = temporary_source
            source_stat = source_path.stat()
            cache_root = Path(os.getenv("CDN_WATERMARK_CACHE_ROOT", "data/runtime/watermarked"))
            cache_root.mkdir(parents=True, exist_ok=True)
            cache_key = hashlib.sha256(
                f"CDNWM6:{source_path.resolve()}:{source_stat.st_mtime_ns}:{source_stat.st_size}:"
                f"{hashlib.sha256(self.secret_key.encode('utf-8')).hexdigest()}:{token}:"
                f"{QIM_STEP if algorithm == 'qim2' else VIDEO_STRENGTH}:{algorithm}".encode("utf-8")
            ).hexdigest()[:32]
            destination = cache_root / f"{cache_key}.mp4"
            if not destination.is_file() or destination.stat().st_size == 0:
                partial = destination.with_suffix(".part.mp4")
                try:
                    embed_video(
                        source_path,
                        partial,
                        token,
                        self.watermark_service.visual_secret_for_token(token),
                        strength=QIM_STEP if algorithm == "qim2" else VIDEO_STRENGTH,
                        adaptive=True,
                        algorithm=algorithm,
                    )
                    partial.replace(destination)
                finally:
                    if partial.exists():
                        partial.unlink()
            return destination.read_bytes()
        finally:
            # The fallback source is content-addressed and can be reused; it
            # is intentionally retained as a bounded runtime cache.
            del temporary_source

    def stream(self, client_id: str, chunk_number: int, video_id: str | None = None) -> dict:
        video_id = video_id or default_content_id()
        reservation = None
        failed = False
        try:
            if self.fault["offline"]:
                raise RuntimeError(f"Nó {self.server_id} está offline por injeção de falha")
            if random.random() < self.fault["drop_rate"]:
                raise RuntimeError(f"mensagem perdida no nó {self.server_id}")
            if self.repository.is_blacklisted(client_id):
                raise PermissionError(f"Cliente {client_id} bloqueado no nó {self.server_id}")
            reservation = self.repository.begin_request(
                self.capacity_profile.max_concurrent_requests,
                self.capacity_profile.max_queue_depth,
                queue_wait_ms(self.capacity_profile, self.repository.request_metrics().get("requests_in_flight", 0), self.repository.request_metrics().get("queue_depth", 0)),
            )
            if not reservation["accepted"]:
                raise CapacityRejected(f"Nó {self.server_id} está saturado: fila máxima atingida")
            if reservation["queue_wait_ms"]:
                time.sleep(reservation["queue_wait_ms"] / 1000.0)
            if self.fault["extra_latency_ms"]:
                time.sleep(self.fault["extra_latency_ms"] / 1000.0)
            content, content_type = self.content_provider.get_chunk(video_id, chunk_number)
            claim_content_id = video_id
            algorithm = "adaptive-spread"
            resolver = getattr(self.content_provider, "resolve_asset", None)
            if resolver is not None:
                try:
                    source_path, _source_type = resolver(video_id, chunk_number)
                    limits = probe_video_limits(source_path)
                    if limits["width"] >= 640 and limits["height"] >= 360:
                        algorithm = "qim2"
                    if video_id == DATASET_CONTENT_ID:
                        dataset = DatasetContentProvider()
                        claim_content_id = dataset._content_id(source_path.resolve())
                except (OSError, ValueError, FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    pass
            if os.getenv("CDN_FORENSIC_CLAIMS", "1").strip().lower() in {"1", "true", "yes", "on"}:
                token, claim = self.watermark_service.issue_forensic_claim(
                    client_id=client_id,
                    server_id=self.server_id,
                    content_id=claim_content_id,
                    session_id=f"sess-{uuid.uuid4().hex}",
                    segment_range=f"{chunk_number}-{chunk_number}",
                    algorithm_id="dct-qim-v2" if algorithm == "qim2" else "adaptive-spread-v5",
                )
                chunk_id = claim.segment_range
            else:
                token, claim = self.watermark_service.issue(client_id, self.server_id, chunk_number, claim_content_id)
                chunk_id = claim.chunk_id
                algorithm = "adaptive-spread"
            watermarked = self._watermarked_media(video_id, chunk_number, token, content, content_type, algorithm)
            result = {
                "chunk_id": chunk_id,
                "content_type": content_type,
                "payload": encode_payload(watermarked),
                "watermark_token": token,
                "server_id": self.server_id,
                "issued_at": claim.issued_at,
            }
        except Exception:
            failed = True
            raise
        finally:
            if reservation and reservation.get("accepted"):
                self.repository.finish_request(failed=failed, queued=bool(reservation.get("queued")))
        result["load"] = self.repository.load()
        result["queue_wait_ms"] = reservation.get("queue_wait_ms", 0.0) if reservation else 0.0
        return result

    def _validate_entry(self, entry: dict) -> None:
        token = entry.get("proof_token")
        if not isinstance(token, str) or not token:
            raise ValueError("prova HMAC ausente")
        claim = self.watermark_service.verify(token)
        if claim.client_id != entry.get("client_id") or claim.server_id != entry.get("watermark_server_id"):
            raise ValueError("prova não corresponde à identidade informada")
        if claim.signature != entry.get("proof_signature"):
            raise ValueError("assinatura da prova não corresponde ao token")

    def accept_blacklist(self, entry: dict, visited: list[str] | None = None, message: dict | None = None) -> dict:
        self._validate_entry(entry)
        visited = list(dict.fromkeys((visited or []) + [self.server_id]))
        message = message or {}
        message_id = str(message.get("message_id") or f"blacklist-{entry.get('client_id')}-{entry.get('proof_signature')}")
        if not self.repository.mark_message_seen(message_id):
            return {"accepted": True, "already_present": True, "propagated_to": [self.server_id], "message_trace": [], "message_id": message_id}
        self.repository.record_message({"received_at": time.time(), "message_type": message.get("message_type", "BLACKLIST_ALERT"), "message_id": message.get("message_id"), "from_server": message.get("from_server"), "client_id": entry.get("client_id")})
        is_new = self.repository.add_blacklist(entry)
        propagated_to = [self.server_id]
        message_trace: list[dict] = []
        if not is_new:
            return {"accepted": True, "already_present": True, "propagated_to": propagated_to, "message_trace": message_trace}
        if int(message.get("hops", 8)) <= 0:
            return {"accepted": True, "already_present": False, "propagated_to": propagated_to, "message_trace": message_trace, "message_id": message_id}
        for peer in list(self.peers):
            peer_id = peer["server_id"]
            if peer_id in visited:
                continue
            try:
                message_id = message_id
                distance = haversine_km(self.latitude, self.longitude, peer["latitude"], peer["longitude"])
                sleep_for_distance(distance, self.latency_factor)
                payload = {"entry": entry, "visited": visited, "message": {"message_id": message_id, "message_type": "BLACKLIST_ALERT", "from_server": self.server_id, "to_server": peer_id, "hops": max(0, int(message.get("hops", 8)) - 1)}}
                response_body = self._post_peer(peer, "/internal/blacklist", payload)
                propagated_to.extend(response_body.get("propagated_to", []))
                message_trace.append({"message_id": message_id, "message_type": "BLACKLIST_ALERT", "from_server": self.server_id, "to_server": peer_id, "client_id": entry.get("client_id"), "status": "delivered", "payload_summary": "client_id + HMAC proof + issue time"})
                message_trace.extend(response_body.get("message_trace", []))
            except (requests.RequestException, ValueError, TypeError):
                pending = {"key": f"{message_id}:{peer_id}", "peer": peer, "entry": entry, "visited": visited, "message": {"message_id": message_id, "message_type": "BLACKLIST_ALERT", "from_server": self.server_id, "to_server": peer_id, "hops": max(0, int(message.get("hops", 8)) - 1)}}
                self.repository.queue_message(pending["key"], pending)
                message_trace.append({"message_id": message_id, "message_type": "BLACKLIST_ALERT", "from_server": self.server_id, "to_server": peer_id, "client_id": entry.get("client_id"), "status": "retry_pending", "payload_summary": "client_id + HMAC proof + issue time"})
                continue
        return {"accepted": True, "already_present": False, "propagated_to": list(dict.fromkeys(propagated_to)), "message_trace": message_trace}

    def reconcile_blacklist(self, entries: list[dict]) -> dict:
        accepted = []
        rejected = []
        for entry in entries[:500]:
            try:
                result = self.accept_blacklist(entry, message={"message_id": f"reconcile-{entry.get('client_id')}-{entry.get('proof_signature')}", "message_type": "BLACKLIST_RECONCILIATION", "hops": 8})
                if result.get("accepted"):
                    accepted.append(entry.get("client_id"))
            except (ValueError, KeyError, TypeError) as exc:
                rejected.append({"client_id": entry.get("client_id"), "error": str(exc)})
        return {"accepted": accepted, "rejected": rejected, "server_id": self.server_id}

    def _retry_pending(self) -> None:
        while not self._retry_stop.wait(1.0):
            for pending in self.repository.pending_messages():
                peer = pending.get("peer", {})
                try:
                    payload = {"entry": pending["entry"], "visited": pending.get("visited", []), "message": pending["message"]}
                    self._post_peer(peer, "/internal/blacklist", payload)
                    self.repository.remove_pending(pending["key"])
                except (requests.RequestException, KeyError, ValueError):
                    continue

    def accept_content_telemetry(self, message: dict) -> dict:
        self.repository.record_message({"received_at": time.time(), "encryption": "AES-256-GCM", **message})
        return {"accepted": True, "server_id": self.server_id, "message_id": message.get("message_id"), "encryption": "AES-256-GCM"}


def create_node_app(node: CDNNode) -> Flask:
    app = Flask(f"cdn-node-{node.server_id}")

    def authenticate(payload: object | None = None, *, encrypted_required: bool = False):
        valid, reason = verify_headers(node.secret_key, request.method, request.path, payload, request.headers, node.repository.mark_message_seen)
        if not valid:
            return jsonify({"error": reason}), 401
        if encrypted_required and not is_encrypted_payload(payload):
            return jsonify({"error": "mensagem interna sem envelope AES-256-GCM"}), 403
        return None

    def encrypted_body():
        wire_payload = request.get_json(silent=True) or {}
        denied = authenticate(wire_payload, encrypted_required=True)
        if denied:
            return None, denied
        try:
            return decrypt_payload(wire_payload, node.secret_key, aad=request.path), None
        except ValueError as exc:
            return None, (jsonify({"error": str(exc)}), 400)

    @app.get("/health")
    def health() -> Any:
        """Health check for the controller and orchestration layer."""
        denied = authenticate()
        if denied:
            return denied
        return jsonify({"ok": True, **node.status()})

    @app.get("/internal/status")
    def internal_status() -> Any:
        """Return local node state, including load and blacklist size."""
        denied = authenticate()
        if denied:
            return denied
        return jsonify(node.status())

    @app.post("/internal/peers")
    def internal_peers() -> Any:
        """Configure the peer list used by HTTP gossip."""
        body, denied = encrypted_body()
        if denied:
            return denied
        peers = body.get("peers", [])
        if not isinstance(peers, list) or len(peers) > 500:
            return jsonify({"error": "peers deve ser uma lista"}), 400
        if any(not isinstance(peer, dict) or not peer.get("server_id") or not peer.get("url") or not isinstance(peer.get("latitude"), (int, float)) or not isinstance(peer.get("longitude"), (int, float)) for peer in peers):
            return jsonify({"error": "peer inválido"}), 400
        try:
            node.configure_peers(peers)
        except (KeyError, TypeError):
            return jsonify({"error": "peer inválido"}), 400
        return jsonify({"configured": [peer["server_id"] for peer in peers]})

    @app.post("/internal/config")
    def internal_config() -> Any:
        """Update node-local runtime configuration received over HTTP."""
        body, denied = encrypted_body()
        if denied:
            return denied
        try:
            return jsonify(node.configure(body))
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/internal/stream")
    def internal_stream() -> Any:
        """Issue a video chunk with an embedded forensic watermark."""
        client_id = request.args.get("client_id", "")
        try:
            auth_payload = {"client_id": client_id, "chunk": int(request.args.get("chunk", "0")), "video_id": request.args.get("video_id") or default_content_id()}
        except ValueError:
            return jsonify({"error": "chunk deve ser inteiro"}), 400
        denied = authenticate(auth_payload)
        if denied:
            return denied
        chunk_number = auth_payload["chunk"]
        if chunk_number < 0:
            return jsonify({"error": "chunk deve ser maior ou igual a zero"}), 400
        if not client_id:
            return jsonify({"error": "client_id é obrigatório"}), 400
        try:
            return jsonify(node.stream(client_id, chunk_number, auth_payload["video_id"]))
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except CapacityRejected as exc:
            return jsonify({"error": str(exc)}), 429
        except (FileNotFoundError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 503

    @app.get("/internal/media")
    def internal_media() -> Any:
        """Deliver the same marked asset as valid binary media, not JSON text."""
        client_id = request.args.get("client_id", "")
        try:
            auth_payload = {
                "client_id": client_id,
                "chunk": int(request.args.get("chunk", "0")),
                "video_id": request.args.get("video_id") or default_content_id(),
            }
        except ValueError:
            return jsonify({"error": "chunk deve ser inteiro"}), 400
        denied = authenticate(auth_payload)
        if denied:
            return denied
        if auth_payload["chunk"] < 0 or not client_id:
            return jsonify({"error": "client_id e chunk válidos são obrigatórios"}), 400
        try:
            result = node.stream(client_id, auth_payload["chunk"], auth_payload["video_id"])
            raw = base64.b64decode(result["payload"], validate=True)
            response = Response(raw, mimetype=result["content_type"])
            response.headers["X-CDN-Server"] = result["server_id"]
            response.headers["X-Queue-Wait-Ms"] = str(result.get("queue_wait_ms", 0.0))
            return response
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except CapacityRejected as exc:
            return jsonify({"error": str(exc)}), 429
        except (FileNotFoundError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 503

    @app.post("/internal/blacklist")
    def internal_blacklist() -> Any:
        """Accept a validated blacklist entry and propagate it over HTTP gossip."""
        body, denied = encrypted_body()
        if denied:
            return denied
        entry = body.get("entry", body)
        if not isinstance(entry, dict) or not entry.get("client_id"):
            return jsonify({"error": "entry de blacklist inválida"}), 400
        try:
            return jsonify(node.accept_blacklist(entry, body.get("visited", []), body.get("message", {})))
        except (ValueError, KeyError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 403

    @app.post("/internal/blacklist/reconcile")
    def internal_blacklist_reconcile() -> Any:
        body, denied = encrypted_body()
        if denied:
            return denied
        entries = body.get("entries", [])
        if not isinstance(entries, list):
            return jsonify({"error": "entries deve ser uma lista"}), 400
        return jsonify(node.reconcile_blacklist(entries))

    @app.post("/internal/content-telemetry")
    def internal_content_telemetry() -> Any:
        """Receive cross-region playback/content telemetry from another CDN node."""
        body, denied = encrypted_body()
        if denied:
            return denied
        if not body.get("message_id") or not body.get("content_id"):
            return jsonify({"error": "telemetria de conteúdo inválida"}), 400
        return jsonify(node.accept_content_telemetry(body))

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Processo independente de um nó CDN")
    parser.add_argument("--node", action="store_true")
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--latency-factor", type=float, default=1.0)
    parser.add_argument("--capacity-tier", choices=["basic", "standard", "pro", "enterprise"], default="basic")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    secret_key = os.getenv("CDN_NODE_SECRET", "local-development-secret")
    node = CDNNode(
        server_id=args.server_id,
        host=args.host,
        port=args.port,
        latitude=args.latitude,
        longitude=args.longitude,
        city=args.city,
        secret_key=secret_key,
        latency_factor=args.latency_factor,
        capacity_tier=args.capacity_tier,
    )
    create_node_app(node).run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()

