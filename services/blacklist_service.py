from __future__ import annotations

import time
import threading
import uuid
import requests

from models.entities import BlacklistEntry, SimulationState
from repositories.in_memory import SimulationRepository
from services.cdn_http_client import CDNHttpClient
from services.watermark_service import WatermarkService
from utils.geo import rank_delivery_servers


class BlacklistService:
    def __init__(self, repository: SimulationRepository, http_client: CDNHttpClient, watermark_service: WatermarkService) -> None:
        self._repository = repository
        self._http_client = http_client
        self._watermark_service = watermark_service
        self._lock = threading.Lock()

    def quarantine(self, client_id: str, reason: str = "forensic analysis pending") -> dict:
        """Create a leased, distributed delivery block before a verdict.

        The lease is deliberately independent of the permanent blacklist. It
        can be renewed or moved to another healthy monitor, and it expires if
        the investigation cannot make progress.
        """
        state = self._repository.state_ref()
        now = time.time()
        existing = state.temporary_blacklist.get(client_id)
        if existing and float(existing.get("expires_at", 0)) > now:
            return existing
        client = state.clients.get(client_id)
        if client is None:
            raise KeyError("client not found")
        candidates = rank_delivery_servers(client.latitude, client.longitude, state.servers.values())
        owner = candidates[0][1] if candidates else None
        lease_seconds = max(30.0, float(state.config.get("forensic_quarantine_seconds", 120.0)))
        entry = {
            "client_id": client_id,
            "quarantine_id": f"quarantine-{uuid.uuid4().hex[:16]}",
            "reason": reason,
            "issued_at": now,
            "expires_at": now + lease_seconds,
            "lease_seconds": lease_seconds,
            "owner_server_id": owner.server_id if owner else None,
            "state": "ANALYZING",
        }
        state.temporary_blacklist[client_id] = entry
        state.forensic_pending_clients.add(client_id)
        self._publish_temporary(entry)
        self._repository.append_event({
            "type": "temporary_blacklist_created",
            "at": now,
            "client_id": client_id,
            "server_id": entry["owner_server_id"],
            "expires_at": entry["expires_at"],
            "communication_kind": "blacklist",
            "trace_id": f"trace-{entry['quarantine_id']}",
        })
        return entry

    def release_quarantine(self, client_id: str, reason: str = "forensic analysis finished") -> None:
        state = self._repository.state_ref()
        entry = state.temporary_blacklist.pop(client_id, None)
        state.forensic_pending_clients.discard(client_id)
        if not entry:
            return
        self._publish_temporary_release(entry)
        self._repository.append_event({
            "type": "temporary_blacklist_released",
            "at": time.time(),
            "client_id": client_id,
            "server_id": entry.get("owner_server_id"),
            "reason": reason,
            "communication_kind": "blacklist",
            "trace_id": f"trace-{entry.get('quarantine_id', client_id)}",
        })

    def maintain_quarantines(self) -> list[dict]:
        """Expire failed leases or transfer their investigation to a live node."""
        state = self._repository.state_ref()
        now = time.time()
        actions: list[dict] = []
        for client_id, entry in list(state.temporary_blacklist.items()):
            if float(entry.get("expires_at", 0)) <= now:
                self.release_quarantine(client_id, "forensic lease expired")
                actions.append({"client_id": client_id, "action": "expired"})
                continue
            owner = state.servers.get(str(entry.get("owner_server_id") or ""))
            if owner and owner.status in {"healthy", "degraded", "overloaded"}:
                available = {
                    server.server_id for server in state.servers.values()
                    if server.process_mode == "http" and server.status != "offline"
                }
                if not available.issubset(set(entry.get("propagated_to", []))):
                    self._publish_temporary(entry)
                continue
            client = state.clients.get(client_id)
            candidates = rank_delivery_servers(client.latitude, client.longitude, state.servers.values()) if client else []
            if not candidates:
                continue
            replacement = candidates[0][1]
            if replacement.server_id == entry.get("owner_server_id"):
                continue
            entry["owner_server_id"] = replacement.server_id
            entry["reassigned_at"] = now
            self._publish_temporary(entry)
            self._repository.append_event({
                "type": "temporary_blacklist_reassigned",
                "at": now,
                "client_id": client_id,
                "server_id": replacement.server_id,
                "communication_kind": "blacklist",
                "trace_id": f"trace-{entry.get('quarantine_id', client_id)}",
            })
            actions.append({"client_id": client_id, "action": "reassigned", "server_id": replacement.server_id})
        return actions

    def _publish_temporary(self, entry: dict) -> None:
        state = self._repository.state_ref()
        propagated_to: list[str] = []
        for server in state.servers.values():
            if server.process_mode != "http" or server.status == "offline":
                continue
            try:
                self._http_client.submit_temporary_blacklist(server, entry)
                propagated_to.append(server.server_id)
                self._repository.append_event({
                    "type": "server_message",
                    "at": time.time(),
                    "message_id": f"temporary-blacklist-{entry['quarantine_id']}-{server.server_id}",
                    "message_type": "TEMPORARY_BLACKLIST_ALERT",
                    "communication_kind": "blacklist",
                    "from_server": entry.get("owner_server_id") or "controller",
                    "to_server": server.server_id,
                    "server_id": server.server_id,
                    "client_id": entry["client_id"],
                    "status": "delivered",
                    "trace_id": f"trace-{entry['quarantine_id']}",
                })
            except (requests.RequestException, OSError):
                continue
        entry["propagated_to"] = sorted(set(propagated_to))

    def _publish_temporary_release(self, entry: dict) -> None:
        state = self._repository.state_ref()
        for server in state.servers.values():
            if server.process_mode != "http" or server.status == "offline":
                continue
            try:
                self._http_client.release_temporary_blacklist(server, entry)
            except (requests.RequestException, OSError):
                continue

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
            self.release_quarantine(claim.client_id, "permanent forensic verdict")
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

