from __future__ import annotations

import time
import threading
import requests

from models.entities import BlacklistEntry, SimulationState
from repositories.in_memory import SimulationRepository
from services.cdn_http_client import CDNHttpClient
from services.watermark_service import WatermarkService


class BlacklistService:
    def __init__(self, repository: SimulationRepository, http_client: CDNHttpClient, watermark_service: WatermarkService) -> None:
        self._repository = repository
        self._http_client = http_client
        self._watermark_service = watermark_service
        self._lock = threading.Lock()

    def report(self, token: str, reason: str = "vazamento detectado pelo monitor", detected_by_server_id: str | None = None, trace_id: str | None = None) -> BlacklistEntry:
        claim = self._watermark_service.verify(token)
        state = self._repository.state_ref()
        client = state.clients.get(claim.client_id)
        watermark_server = state.servers.get(claim.server_id)
        detecting_server = state.servers.get(detected_by_server_id or claim.server_id)
        if client is None or watermark_server is None or detecting_server is None:
            raise ValueError("A prova aponta para um cliente ou servidor inexistente")
        with self._lock:
            existing = state.blacklist.get(claim.client_id)
            if existing:
                return existing
            entry = BlacklistEntry(
                client_id=claim.client_id,
                reason=reason,
                detected_at=time.time(),
                watermark_issued_at=claim.issued_at,
                server_id=detecting_server.server_id,
                proof_signature=claim.signature,
                watermark_server_id=claim.server_id,
                proof_token=token,
            )
            self._repository.add_blacklist(entry)
            client.active = False
        try:
            result = self._http_client.submit_blacklist(detecting_server, entry.to_internal_dict())
        except (requests.RequestException, OSError) as exc:
            result = {"propagated_to": [detecting_server.server_id], "message_trace": [{"message_id": f"blacklist-{entry.client_id}-{entry.proof_signature}", "message_type": "BLACKLIST_ALERT", "from_server": "monitor", "to_server": detecting_server.server_id, "status": "retry_pending", "error": str(exc)}]}
            self._repository.append_event({"type": "blacklist_propagation_failed", "at": time.time(), "client_id": entry.client_id, "server_id": detecting_server.server_id, "error": str(exc), "trace_id": trace_id or f"trace-{entry.client_id}-{entry.proof_signature[:8]}"})
        entry.propagated_to = list(result.get("propagated_to", []))
        state.blacklist[entry.client_id] = entry
        for message in result.get("message_trace", []):
            self._repository.append_event({
                "type": "server_message",
                "at": time.time(),
                "message_id": message.get("message_id"),
                "message_type": message.get("message_type", "BLACKLIST_ALERT"),
                "communication_kind": "blacklist",
                "from_server": message.get("from_server"),
                "to_server": message.get("to_server"),
                "server_id": message.get("to_server"),
                "client_id": entry.client_id,
                "status": message.get("status", "delivered"),
                "payload_summary": message.get("payload_summary", "client_id + HMAC proof + issue time"),
                "protocol": "HTTP/1.1 gossip",
                "encryption": "AES-256-GCM",
                "trace_id": trace_id or f"trace-{entry.client_id}-{entry.proof_signature[:8]}",
            })
        self._repository.append_event({
            "type": "blacklist_propagated",
            "at": entry.detected_at,
            "client_id": entry.client_id,
            "server_id": entry.server_id,
            "watermark_server_id": entry.watermark_server_id,
            "monitor_server_id": entry.server_id,
            "propagated_to": entry.propagated_to,
            "protocol": "HTTP gossip",
            "encryption": "AES-256-GCM",
            "proof_algorithm": "AES-256-GCM + HMAC-SHA256",
            "trace_id": trace_id or f"trace-{entry.client_id}-{entry.proof_signature[:8]}",
        })
        return entry

