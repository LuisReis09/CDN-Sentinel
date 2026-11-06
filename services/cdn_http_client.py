from __future__ import annotations

from typing import Any, Dict
import os
import time

import requests

from models.entities import CDNServer
from utils.latency import sleep_for_distance
from utils.protocol import path_from_url, signed_headers


class CDNHttpClient:
    """HTTP-only adapter for controller-to-node and node-to-node calls."""

    def __init__(self, timeout: float = 2.0, secret_key: str | None = None) -> None:
        self._timeout = timeout
        self._secret_key = secret_key or os.getenv("CDN_SECRET_KEY", "local-development-secret")

    def configure_secret(self, secret_key: str) -> None:
        self._secret_key = secret_key

    def _headers(self, method: str, url: str, payload: object | None = None) -> dict[str, str]:
        return signed_headers(self._secret_key, method, path_from_url(url), payload)

    def health(self, server: CDNServer) -> Dict[str, Any]:
        url = f"{server.url}/health"
        response = requests.get(url, headers=self._headers("GET", url), timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def configure_peers(self, server: CDNServer, peers: list[dict]) -> Dict[str, Any]:
        url = f"{server.url}/internal/peers"
        payload = {"peers": peers}
        response = requests.post(url, json=payload, headers=self._headers("POST", url, payload), timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def configure(self, server: CDNServer, values: dict) -> Dict[str, Any]:
        url = f"{server.url}/internal/config"
        response = requests.post(url, json=values, headers=self._headers("POST", url, values), timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def stream(self, server: CDNServer, client_id: str, chunk_number: int, distance_km: float, latency_factor: float, video_id: str = "bigbuckbunny") -> Dict[str, Any]:
        delay = sleep_for_distance(distance_km, latency_factor)
        url = f"{server.url}/internal/stream"
        started = time.monotonic()
        params = {"client_id": client_id, "chunk": chunk_number, "video_id": video_id}
        response = requests.get(
            url,
            params=params,
            headers=self._headers("GET", url, params),
            timeout=self._timeout,
        )
        response.raise_for_status()
        result = response.json()
        result["network_latency_ms"] = round(delay * 1000, 3)
        result["http_rtt_ms"] = round((time.monotonic() - started) * 1000, 3)
        return result

    def submit_blacklist(self, server: CDNServer, entry: dict) -> Dict[str, Any]:
        url = f"{server.url}/internal/blacklist"
        payload = {
                "entry": entry,
                "message": {
                    "message_id": f"blacklist-{entry.get('client_id')}-{int(entry.get('detected_at', 0) * 1000)}",
                    "message_type": "BLACKLIST_ALERT",
                    "from_server": "monitor",
                    "to_server": server.server_id,
                },
            }
        response = requests.post(
            url,
            json=payload,
            headers=self._headers("POST", url, payload),
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def publish_content_telemetry(self, server: CDNServer, message: dict) -> Dict[str, Any]:
        url = f"{server.url}/internal/content-telemetry"
        response = requests.post(url, json=message, headers=self._headers("POST", url, message), timeout=min(self._timeout, 4.0))
        response.raise_for_status()
        return response.json()

    def status(self, server: CDNServer) -> Dict[str, Any]:
        url = f"{server.url}/internal/status"
        response = requests.get(url, headers=self._headers("GET", url), timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def reconcile_blacklist(self, server: CDNServer, entries: list[dict]) -> Dict[str, Any]:
        url = f"{server.url}/internal/blacklist/reconcile"
        payload = {"entries": entries}
        response = requests.post(url, json=payload, headers=self._headers("POST", url, payload), timeout=self._timeout)
        response.raise_for_status()
        return response.json()

