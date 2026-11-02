from __future__ import annotations

from typing import Any, Dict

import requests

from models.entities import CDNServer
from utils.latency import sleep_for_distance


class CDNHttpClient:
    """HTTP-only adapter for controller-to-node and node-to-node calls."""

    def __init__(self, timeout: float = 8.0) -> None:
        self._timeout = timeout

    def health(self, server: CDNServer) -> Dict[str, Any]:
        response = requests.get(f"{server.url}/health", timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def configure_peers(self, server: CDNServer, peers: list[dict]) -> Dict[str, Any]:
        response = requests.post(f"{server.url}/internal/peers", json={"peers": peers}, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def configure(self, server: CDNServer, values: dict) -> Dict[str, Any]:
        response = requests.post(f"{server.url}/internal/config", json=values, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def stream(self, server: CDNServer, client_id: str, chunk_number: int, distance_km: float, latency_factor: float) -> Dict[str, Any]:
        delay = sleep_for_distance(distance_km, latency_factor)
        response = requests.get(
            f"{server.url}/internal/stream",
            params={"client_id": client_id, "chunk": chunk_number},
            timeout=self._timeout,
        )
        response.raise_for_status()
        result = response.json()
        result["network_latency_ms"] = round(delay * 1000, 3)
        return result

    def submit_blacklist(self, server: CDNServer, entry: dict) -> Dict[str, Any]:
        response = requests.post(f"{server.url}/internal/blacklist", json=entry, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def status(self, server: CDNServer) -> Dict[str, Any]:
        response = requests.get(f"{server.url}/internal/status", timeout=self._timeout)
        response.raise_for_status()
        return response.json()

