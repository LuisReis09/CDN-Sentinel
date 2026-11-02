from __future__ import annotations

import time

from models.entities import BlacklistEntry, SimulationState
from repositories.in_memory import SimulationRepository
from services.cdn_http_client import CDNHttpClient
from services.watermark_service import WatermarkService


class BlacklistService:
    def __init__(self, repository: SimulationRepository, http_client: CDNHttpClient, watermark_service: WatermarkService) -> None:
        self._repository = repository
        self._http_client = http_client
        self._watermark_service = watermark_service

    def report(self, token: str, reason: str = "vazamento detectado pelo monitor") -> BlacklistEntry:
        claim = self._watermark_service.verify(token)
        state = self._repository.snapshot()
        client = state.clients.get(claim.client_id)
        server = state.servers.get(claim.server_id)
        if client is None or server is None:
            raise ValueError("A prova aponta para um cliente ou servidor inexistente")
        existing = state.blacklist.get(claim.client_id)
        if existing:
            return existing
        entry = BlacklistEntry(
            client_id=claim.client_id,
            reason=reason,
            detected_at=time.time(),
            watermark_issued_at=claim.issued_at,
            server_id=claim.server_id,
            proof_signature=claim.signature,
        )
        self._repository.add_blacklist(entry)
        client.active = False
        result = self._http_client.submit_blacklist(server, entry.to_dict())
        entry.propagated_to = list(result.get("propagated_to", []))
        state.blacklist[entry.client_id] = entry
        self._repository.append_event({
            "type": "blacklist_propagated",
            "at": entry.detected_at,
            "client_id": entry.client_id,
            "server_id": entry.server_id,
            "propagated_to": entry.propagated_to,
            "protocol": "HTTP gossip",
            "proof_algorithm": "HMAC-SHA256",
        })
        return entry

