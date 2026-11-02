from __future__ import annotations

import time

from models.entities import Client, SimulationState, VideoChunk
from services.cdn_http_client import CDNHttpClient
from utils.geo import choose_server


class SimulationPausedError(RuntimeError):
    """Raised when streaming is requested while the simulation is paused."""


class ClientOfflineError(RuntimeError):
    """Raised when a disconnected simulated client requests a stream."""


class StreamService:
    def __init__(self, http_client: CDNHttpClient, repository=None) -> None:
        self._http_client = http_client
        self._repository = repository

    def stream(self, client: Client, state: SimulationState, chunk_number: int = 0) -> VideoChunk:
        if client.client_id in state.blacklist:
            raise PermissionError(f"Cliente {client.client_id} está na blacklist")
        if state.paused:
            raise SimulationPausedError("A simulação está pausada")
        if not client.online:
            raise ClientOfflineError(f"Cliente {client.client_id} está offline")
        server, distance = choose_server(client.latitude, client.longitude, state.servers.values())
        result = self._http_client.stream(
            server,
            client.client_id,
            chunk_number,
            distance,
            float(state.config["latency_factor"]),
        )
        server.load = int(result.get("load", server.load))
        client.videos_consumed += 1
        client.last_activity_at = time.time()
        if self._repository:
            self._repository.append_traffic({
                "at": time.time(),
                "client_id": client.client_id,
                "server_id": server.server_id,
                "distance_km": round(distance, 2),
                "latency_ms": float(result["network_latency_ms"]),
                "chunk_id": result["chunk_id"],
            })
            self._repository.append_event({
                "type": "client_request",
                "at": time.time(),
                "client_id": client.client_id,
                "server_id": server.server_id,
                "latency_ms": float(result["network_latency_ms"]),
                "protocol": "HTTP/1.1",
                "routing": "Haversine / nearest healthy CDN",
                "watermark_algorithm": "HMAC-SHA256",
                "chunk_id": result["chunk_id"],
            })
        return VideoChunk(
            chunk_id=result["chunk_id"],
            content_type=result["content_type"],
            payload=result["payload"],
            watermark_token=result["watermark_token"],
            server_id=result["server_id"],
            client_id=client.client_id,
            issued_at=float(result["issued_at"]),
            latency_ms=float(result["network_latency_ms"]),
        )

