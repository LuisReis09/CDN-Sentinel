from __future__ import annotations

import random
import threading
import time

from repositories.in_memory import SimulationRepository
from services.stream_service import ClientOfflineError, SimulationPausedError, StreamService


class ClientActivityService:
    """Creates a visible stream of client arrivals, sessions and departures."""

    def __init__(self, repository: SimulationRepository, stream_service: StreamService, interval_seconds: float = 2.5) -> None:
        self._repository = repository
        self._stream_service = stream_service
        self._interval_seconds = interval_seconds
        self._random = random.Random(20261101)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="client-activity-simulator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            state = self._repository.snapshot()
            if not state.initialized or state.paused:
                continue
            clients = [client for client in state.clients.values() if client.active]
            for client in clients:
                if not client.online and self._random.random() < 0.35:
                    client.online = True
                    self._repository.append_event({"type": "client_connected", "at": time.time(), "client_id": client.client_id})
                if not client.online:
                    continue
                try:
                    self._stream_service.stream(client, state, chunk_number=client.videos_consumed % 5)
                    if self._random.random() < 0.25:
                        client.online = False
                        self._repository.append_event({"type": "client_disconnected", "at": time.time(), "client_id": client.client_id, "videos_consumed": client.videos_consumed})
                except (ClientOfflineError, PermissionError, RuntimeError, OSError):
                    continue

