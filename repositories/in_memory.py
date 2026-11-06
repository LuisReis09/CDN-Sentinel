from __future__ import annotations

import time
import copy
import uuid
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

from models.entities import BlacklistEntry, Client, CDNServer, SimulationState


class SimulationRepository:
    """Thread-safe state repository owned by the controller process."""

    def __init__(self) -> None:
        self._state = SimulationState()
        self._history: List[dict] = []
        self._lock = RLock()

    def replace(self, state: SimulationState) -> None:
        with self._lock:
            if not state.simulation_id:
                state.simulation_id = f"sim-{uuid.uuid4().hex[:12]}"
            self._state = state

    def archive_current(self, ended_at: float | None = None, reason: str = "operator") -> dict | None:
        with self._lock:
            if not self._state.initialized or self._state.lifecycle == "idle":
                return None
            record = copy.deepcopy(self._state)
            record.ended_at = ended_at or time.time()
            record.end_reason = reason
            record.lifecycle = "ended"
            payload = {
                "simulation_id": record.simulation_id,
                "lifecycle": record.lifecycle,
                "started_at": record.started_at,
                "ended_at": record.ended_at,
                "end_reason": record.end_reason,
                "configuration": record.config,
                "servers": [server.to_dict() for server in record.servers.values()],
                "clients": [client.to_dict() for client in record.clients.values()],
                "blacklist": [entry.to_dict() for entry in record.blacklist.values()],
                "leaks": copy.deepcopy(record.leaks),
                "events": copy.deepcopy(record.events),
                "traffic": copy.deepcopy(record.traffic),
                "scan_history": copy.deepcopy(record.scan_history),
            }
            self._history.append(payload)
            self._history = self._history[-20:]
            return copy.deepcopy(payload)

    def history(self, simulation_id: str | None = None) -> list[dict]:
        with self._lock:
            records = self._history if simulation_id is None else [item for item in self._history if item.get("simulation_id") == simulation_id]
            return copy.deepcopy(records)

    def snapshot(self) -> SimulationState:
        """Return an isolated read snapshot; callers cannot mutate live state."""
        with self._lock:
            return copy.deepcopy(self._state)

    def state_ref(self) -> SimulationState:
        """Return the live state for short, repository-owned mutations only.

        Services use this only while performing an atomic operation. API readers
        must use :meth:`snapshot`.
        """
        with self._lock:
            return self._state

    def get_client(self, client_id: str) -> Optional[Client]:
        with self._lock:
            return copy.deepcopy(self._state.clients.get(client_id))

    def get_server(self, server_id: str) -> Optional[CDNServer]:
        with self._lock:
            return copy.deepcopy(self._state.servers.get(server_id))

    def add_client(self, client: Client) -> None:
        with self._lock:
            if client.client_id in self._state.clients:
                raise ValueError(f"Cliente {client.client_id} já existe")
            self._state.clients[client.client_id] = client

    def update_client(self, client: Client) -> None:
        with self._lock:
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
            self._state.blacklist[entry.client_id] = copy.deepcopy(entry)

    def append_leak(self, leak: dict) -> None:
        with self._lock:
            self._state.leaks.append(copy.deepcopy(leak))
            self._state.leaks = self._state.leaks[-500:]

    def replace_leaks(self, leaks: List[dict]) -> None:
        with self._lock:
            self._state.leaks = leaks

    def update_leak(self, leak_id: str, values: Dict[str, Any]) -> bool:
        with self._lock:
            for leak in self._state.leaks:
                if leak.get("leak_id") == leak_id:
                    leak.update(copy.deepcopy(values))
                    return True
            return False

    def blacklist_values(self) -> List[BlacklistEntry]:
        with self._lock:
            return copy.deepcopy(list(self._state.blacklist.values()))

    def update_config(self, values: Dict[str, Any]) -> None:
        with self._lock:
            self._state.config.update(values)
            self._state.updated_at = time.time()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._state.paused = paused
            self._state.lifecycle = "paused" if paused else "running"
            self._state.updated_at = time.time()

    def append_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            enriched = copy.deepcopy(event)
            enriched.setdefault("at", time.time())
            enriched.setdefault("timestamp", enriched["at"])
            enriched.setdefault("simulation_id", self._state.simulation_id)
            enriched.setdefault("trace_id", enriched.get("request_id") or f"trace-{uuid.uuid4().hex[:16]}")
            enriched.setdefault("event_id", f"evt-{uuid.uuid4().hex[:12]}")
            self._state.events.append(enriched)
            self._state.events = self._state.events[-500:]

    def append_traffic(self, traffic: Dict[str, Any]) -> None:
        with self._lock:
            self._state.traffic.append(copy.deepcopy(traffic))
            self._state.traffic = self._state.traffic[-500:]

    def reset_metrics(self) -> None:
        with self._lock:
            self._state.events = [event for event in self._state.events if event.get("type") == "simulation_initialized"][-1:]
            self._state.traffic.clear()
            self._state.scan_history.clear()


class NodeRepository:
    """Local repository. Each CDN process has its own instance and memory."""

    def __init__(self) -> None:
        self._blacklist: Dict[str, dict] = {}
        self._load = 0
        self._messages: List[dict] = []
        self._seen_messages: Dict[str, float] = {}
        self._pending_messages: Dict[str, dict] = {}
        self._requests_total = 0
        self._errors_total = 0
        self._consecutive_errors = 0
        self._in_flight = 0
        self._last_request_at: float | None = None
        self._lock = RLock()

    def is_blacklisted(self, client_id: str) -> bool:
        with self._lock:
            return client_id in self._blacklist

    def add_blacklist(self, entry: dict) -> bool:
        with self._lock:
            was_new = entry["client_id"] not in self._blacklist
            self._blacklist[entry["client_id"]] = copy.deepcopy(entry)
            return was_new

    def blacklist(self) -> List[dict]:
        with self._lock:
            return copy.deepcopy(list(self._blacklist.values()))

    def mark_message_seen(self, message_id: str, ttl_seconds: float = 300.0) -> bool:
        now = time.time()
        with self._lock:
            self._seen_messages = {key: value for key, value in self._seen_messages.items() if value > now}
            if message_id in self._seen_messages:
                return False
            self._seen_messages[message_id] = now + ttl_seconds
            return True

    def queue_message(self, key: str, payload: dict) -> None:
        with self._lock:
            self._pending_messages[key] = copy.deepcopy(payload)

    def pending_messages(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(list(self._pending_messages.values()))

    def remove_pending(self, key: str) -> None:
        with self._lock:
            self._pending_messages.pop(key, None)

    def begin_request(self) -> None:
        with self._lock:
            self._requests_total += 1
            self._in_flight += 1
            self._last_request_at = time.time()

    def finish_request(self, failed: bool = False) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            if failed:
                self._errors_total += 1
                self._consecutive_errors += 1
            else:
                self._consecutive_errors = 0

    def request_metrics(self) -> dict:
        with self._lock:
            return {"requests_total": self._requests_total, "errors_total": self._errors_total, "requests_in_flight": self._in_flight, "last_request_at": self._last_request_at, "consecutive_errors": self._consecutive_errors}

    def clear_consecutive_errors(self) -> None:
        with self._lock:
            self._consecutive_errors = 0

    def increment_load(self) -> None:
        with self._lock:
            self._load += 1

    def decrement_load(self) -> None:
        with self._lock:
            self._load = max(0, self._load - 1)

    def load(self) -> int:
        with self._lock:
            return self._load

    def record_message(self, message: dict) -> None:
        with self._lock:
            self._messages.append(message)
            self._messages = self._messages[-200:]

    def message_count(self) -> int:
        with self._lock:
            return len(self._messages)

