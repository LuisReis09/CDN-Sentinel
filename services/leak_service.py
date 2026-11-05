from __future__ import annotations

import threading
import time
import random
import uuid
from typing import Callable

from models.entities import SimulationState
from repositories.in_memory import SimulationRepository
from services.stream_service import StreamService


class LeakService:
    """Background simulator for malicious clients and external platforms."""

    def __init__(self, repository: SimulationRepository, stream_service: StreamService, interval_seconds: float = 4.0) -> None:
        self._repository = repository
        self._stream_service = stream_service
        self._interval_seconds = interval_seconds
        self._tick_interval_seconds = interval_seconds
        self._random = random.Random(20261102)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, tick_interval_seconds: float = 2.5) -> None:
        self.stop()
        self._tick_interval_seconds = max(0.25, float(tick_interval_seconds))
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="leak-simulator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self._tick_interval_seconds * 2):
            state = self._repository.snapshot()
            if state.paused:
                continue
            malicious = [client for client in state.clients.values() if client.malicious and client.active]
            for client in malicious:
                if client.client_id in state.blacklist:
                    continue
                try:
                    chunk = self._stream_service.stream(client, state, chunk_number=1)
                    platform = self._random.choice([
                        {"id": "mirrorflix", "name": "MirrorFlix", "kind": "vídeo espelho"},
                        {"id": "streambox", "name": "StreamBox", "kind": "retransmissão não autorizada"},
                        {"id": "torrent-index", "name": "Torrent Index", "kind": "índice de distribuição"},
                    ])
                    self._repository.append_leak({
                        "leak_id": f"leak-{uuid.uuid4().hex[:12]}",
                        "client_id": client.client_id,
                        "server_id": chunk.server_id,
                        "origin_server_id": chunk.server_id,
                        "platform": platform["name"],
                        "platform_id": platform["id"],
                        "platform_kind": platform["kind"],
                        "external_url": f"https://simulated.example/{platform['id']}/{client.client_id}/{chunk.chunk_id}",
                        "watermark_token": chunk.watermark_token,
                        "content": chunk.payload,
                        "created_at": time.time(),
                        "processed": False,
                    })
                except (PermissionError, RuntimeError, OSError):
                    continue

