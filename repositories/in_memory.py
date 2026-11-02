from __future__ import annotations

import time
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

from models.entities import BlacklistEntry, Client, CDNServer, SimulationState


class SimulationRepository:
    """Thread-safe state repository owned by the controller process."""

    def __init__(self) -> None:
        self._state = SimulationState()
        self._lock = RLock()

    def replace(self, state: SimulationState) -> None:
        with self._lock:
            self._state = state

    def snapshot(self) -> SimulationState:
        with self._lock:
            return self._state

    def get_client(self, client_id: str) -> Optional[Client]:
        with self._lock:
            return self._state.clients.get(client_id)

    def get_server(self, server_id: str) -> Optional[CDNServer]:
        with self._lock:
            return self._state.servers.get(server_id)

    def add_client(self, client: Client) -> None:
        with self._lock:
            if client.client_id in self._state.clients:
                raise ValueError(f"Cliente {client.client_id} já existe")
            self._state.clients[client.client_id] = client

    def add_server(self, server: CDNServer) -> None:
        with self._lock:
            if server.server_id in self._state.servers:
                raise ValueError(f"Servidor {server.server_id} já existe")
            if any(existing.port == server.port for existing in self._state.servers.values()):
                raise ValueError(f"A porta {server.port} já está em uso")
            self._state.servers[server.server_id] = server

    def add_blacklist(self, entry: BlacklistEntry) -> None:
        with self._lock:
            self._state.blacklist[entry.client_id] = entry

    def append_leak(self, leak: dict) -> None:
        with self._lock:
            self._state.leaks.append(leak)

    def replace_leaks(self, leaks: List[dict]) -> None:
        with self._lock:
            self._state.leaks = leaks

    def blacklist_values(self) -> List[BlacklistEntry]:
        with self._lock:
            return list(self._state.blacklist.values())

    def update_config(self, values: Dict[str, Any]) -> None:
        with self._lock:
            self._state.config.update(values)
            self._state.updated_at = time.time()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._state.paused = paused
            self._state.updated_at = time.time()

    def append_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            self._state.events.append(event)
            self._state.events = self._state.events[-500:]

    def append_traffic(self, traffic: Dict[str, Any]) -> None:
        with self._lock:
            self._state.traffic.append(traffic)
            self._state.traffic = self._state.traffic[-500:]


class NodeRepository:
    """Local repository. Each CDN process has its own instance and memory."""

    def __init__(self) -> None:
        self._blacklist: Dict[str, dict] = {}
        self._load = 0
        self._lock = RLock()

    def is_blacklisted(self, client_id: str) -> bool:
        with self._lock:
            return client_id in self._blacklist

    def add_blacklist(self, entry: dict) -> bool:
        with self._lock:
            was_new = entry["client_id"] not in self._blacklist
            self._blacklist[entry["client_id"]] = entry
            return was_new

    def blacklist(self) -> List[dict]:
        with self._lock:
            return list(self._blacklist.values())

    def increment_load(self) -> None:
        with self._lock:
            self._load += 1

    def decrement_load(self) -> None:
        with self._lock:
            self._load = max(0, self._load - 1)

    def load(self) -> int:
        with self._lock:
            return self._load

