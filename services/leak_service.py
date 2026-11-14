from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
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

    def __init__(self, repository: SimulationRepository, stream_service: StreamService, interval_seconds: float = 4.0, on_leak: Callable[[dict], None] | None = None) -> None:
        self._repository = repository
        self._stream_service = stream_service
        self._interval_seconds = interval_seconds
        self._tick_interval_seconds = interval_seconds
        self._random = random.Random(20261102)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_leak = on_leak
        self._next_malicious_index = 0

    def set_on_leak(self, callback: Callable[[dict], None] | None) -> None:
        """Notify the monitor after a real, marked leak is persisted."""
        self._on_leak = callback

    def start(self, tick_interval_seconds: float = 1.25) -> None:
        self.stop()
        self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="leak-simulator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def configure_tick_interval(self, tick_interval_seconds: float) -> None:
        """Change the cadence without interrupting the leak worker."""
        self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))

    def _run(self) -> None:
        while not self._stop_event.wait(self._tick_interval_seconds):
            state = self._repository.state_ref()
            if state.paused or state.lifecycle != "running":
                continue
            pending_client_ids = {
                str(leak.get("client_id"))
                for leak in state.leaks
                if not leak.get("processed")
            }
            malicious = [
                client
                for client in state.clients.values()
                if client.malicious
                and client.active
                and client.client_id not in state.blacklist
                and client.client_id not in pending_client_ids
            ]
            if not malicious:
                continue
            # Each candidate uses the genuine QIM3/AES delivery and forensic
            # path.  Limit this expensive work to one round-robin client per
            # cycle so a burst cannot starve visible simulation updates or
            # queue a backlog before monitors can inspect the first leak.
            malicious.sort(key=lambda item: item.client_id)
            client = malicious[self._next_malicious_index % len(malicious)]
            self._next_malicious_index += 1
            try:
                chunk = self._stream_service.stream(client, state, chunk_number=1)
                try:
                    media = base64.b64decode(chunk.payload, validate=True)
                except (ValueError, TypeError):
                    continue
                leak_root = Path(os.getenv("CDN_LEAK_MEDIA_ROOT", "data/runtime/leaks"))
                leak_root.mkdir(parents=True, exist_ok=True)
                leak_id = f"leak-{uuid.uuid4().hex[:12]}"
                media_path = leak_root / f"{leak_id}.mp4"
                media_path.write_bytes(media)
                platform = self._random.choice([
                    {"id": "mirrorflix", "name": "MirrorFlix", "kind": "vídeo espelho"},
                    {"id": "streambox", "name": "StreamBox", "kind": "retransmissão não autorizada"},
                    {"id": "torrent-index", "name": "Torrent Index", "kind": "índice de distribuição"},
                ])
                leak = {
                    "leak_id": leak_id,
                    "client_id": client.client_id,
                    "server_id": chunk.server_id,
                    "origin_server_id": chunk.server_id,
                    "platform": platform["name"],
                    "platform_id": platform["id"],
                    "platform_kind": platform["kind"],
                    "external_url": f"https://simulated.example/{platform['id']}/{leak_id}",
                    "request_id": chunk.request_id,
                    "trace_id": chunk.trace_id,
                    "content_type": chunk.content_type,
                    "media_path": str(media_path.resolve()),
                    "media_sha256": hashlib.sha256(media).hexdigest(),
                    "content": None,
                    "created_at": time.time(),
                    "processed": False,
                    "analyzed": False,
                    "attributed": False,
                    "needs_reanalysis": False,
                    "analysis_count": 0,
                }
                self._repository.append_leak(leak)
                if self._on_leak:
                    self._on_leak(leak)
            except (PermissionError, RuntimeError, OSError):
                continue

