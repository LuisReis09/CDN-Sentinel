from __future__ import annotations

import base64
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
import time
import random
import uuid
from typing import Callable

from repositories.in_memory import SimulationRepository
from services.content_provider import default_content_id
from services.stream_service import StreamService


class LeakService:
    """Capture authentic watermarked leaks without serializing the simulator."""

    def __init__(self, repository: SimulationRepository, stream_service: StreamService, interval_seconds: float = 4.0, on_leak: Callable[[dict], None] | None = None) -> None:
        self._repository = repository
        self._stream_service = stream_service
        self._interval_seconds = interval_seconds
        self._tick_interval_seconds = interval_seconds
        self._random = random.Random(20261102)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._capture_workers = 2
        self._selection_lock = threading.Lock()
        self._on_leak = on_leak
        self._on_quarantine: Callable[[str], object] | None = None
        self._on_quarantine_release: Callable[[str, str], object] | None = None
        self._next_malicious_index = 0

    def set_on_leak(self, callback: Callable[[dict], None] | None) -> None:
        self._on_leak = callback

    def set_on_quarantine(self, callback: Callable[[str], object] | None, release_callback: Callable[[str, str], object] | None = None) -> None:
        self._on_quarantine = callback
        self._on_quarantine_release = release_callback

    def _release_quarantine(self, client_id: str, reason: str) -> None:
        if self._on_quarantine_release:
            self._on_quarantine_release(client_id, reason)
        else:
            state = self._repository.state_ref()
            state.forensic_pending_clients.discard(client_id)
            state.temporary_blacklist.pop(client_id, None)

    def start(self, tick_interval_seconds: float = 1.25) -> None:
        self.stop()
        self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))
        state = self._repository.state_ref()
        configured_workers = int(state.config.get("forensic_capture_workers", 2) or 2)
        if str(state.config.get("simulation_profile", "realistic")) == "fast":
            configured_workers = max(configured_workers, 3)
        self._capture_workers = max(1, min(8, configured_workers))
        self._executor = ThreadPoolExecutor(max_workers=self._capture_workers, thread_name_prefix="leak-capture")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="leak-simulator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        executor, self._executor = self._executor, None
        if executor:
            executor.shutdown(wait=True, cancel_futures=True)

    def configure_tick_interval(self, tick_interval_seconds: float) -> None:
        self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._capture_one_leak()
            if self._stop_event.wait(self._tick_interval_seconds):
                break

    def _select_candidates(self, state) -> list:
        now = time.time()
        pending_client_ids = {
            str(leak.get("client_id"))
            for leak in state.leaks
            if not leak.get("processed")
        }
        # A simulated rogue publishes one captured sample per run.  Failed
        # forensic extraction is retried against that immutable sample by the
        # monitor; recapturing a fresh clip after the bounded review finishes
        # would create an endless quarantine/capture loop and make telemetry
        # look like many independent piracy events for one client.
        published_client_ids = {
            str(leak.get("client_id"))
            for leak in state.leaks
            if leak.get("client_id")
        }
        return [
            client for client in state.clients.values()
            if client.malicious
            and client.active
            and client.client_id not in state.blacklist
            and client.client_id not in pending_client_ids
            and client.client_id not in published_client_ids
            and client.client_id not in state.forensic_pending_clients
            and not any(
                client.client_id == cid and float(entry.get("expires_at", 0)) > now
                for cid, entry in state.temporary_blacklist.items()
            )
        ]

    def _capture_one_leak(self) -> None:
        if self._stop_event.is_set():
            return
        state = self._repository.state_ref()
        if state.paused or state.lifecycle != "running":
            return
        with self._selection_lock:
            candidates = sorted(self._select_candidates(state), key=lambda item: item.client_id)
            if not candidates:
                return
            worker_count = min(self._capture_workers, len(candidates))
            start = self._next_malicious_index % len(candidates)
            self._next_malicious_index += worker_count
            selected = [candidates[(start + offset) % len(candidates)] for offset in range(worker_count)]
            eligible = []
            for client in selected:
                # ``malicious`` is the experiment's probability draw.  Once
                # selected, a simulated rogue client must publish one sample;
                # otherwise three additional random gates can make a finite
                # execution report no piracy at all.  The behavioral fields
                # remain telemetry describing the profile, not a second
                # source of truth for guilt.
                behavior_score = (
                    float(getattr(client, "piracy_intent_probability", 1.0) or 0.0)
                    * float(getattr(client, "piracy_attempt_probability", 1.0) or 0.0)
                    * float(getattr(client, "piracy_publish_probability", 1.0) or 0.0)
                )
                if self._on_quarantine:
                    self._on_quarantine(client.client_id)
                else:
                    state.forensic_pending_clients.add(client.client_id)
                    state.temporary_blacklist.setdefault(client.client_id, {
                        "client_id": client.client_id,
                        "issued_at": time.time(),
                        "expires_at": time.time() + 120.0,
                        "state": "ANALYZING",
                    })
                state.forensic_capture_pending_clients.add(client.client_id)
                self._repository.append_event({
                    "type": "piracy_attempt",
                    "at": time.time(),
                    "client_id": client.client_id,
                    "behavior_score": round(behavior_score, 4),
                    "selection_reason": "client classified malicious by seeded experiment draw",
                    "status": "quarantined",
                })
                eligible.append(client)
        if not eligible:
            return
        executor = self._executor
        if executor is None:
            with ThreadPoolExecutor(max_workers=len(eligible), thread_name_prefix="leak-capture-once") as local_executor:
                futures = [local_executor.submit(self._capture_client, client.client_id) for client in eligible]
                for future in as_completed(futures):
                    future.result()
            return
        futures = [executor.submit(self._capture_client, client.client_id) for client in eligible]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                continue

    def _capture_client(self, client_id: str) -> None:
        state = self._repository.state_ref()
        client = state.clients.get(client_id)
        capture_started_at = time.time()
        if client is None or not client.active:
            self._release_quarantine(client_id, "client became unavailable")
            state.forensic_capture_pending_clients.discard(client_id)
            return
        try:
            chunk = self._stream_service.stream(client, state, chunk_number=1, forensic_capture=True)
            try:
                media = base64.b64decode(chunk.payload, validate=True)
            except (ValueError, TypeError):
                self._release_quarantine(client.client_id, "invalid evidence payload")
                return
            leak_root = Path(os.getenv("CDN_LEAK_MEDIA_ROOT", "data/runtime/leaks"))
            leak_root.mkdir(parents=True, exist_ok=True)
            leak_id = f"leak-{uuid.uuid4().hex[:12]}"
            media_path = leak_root / f"{leak_id}.mp4"
            media_path.write_bytes(media)
            platform = self._random.choice([
                {"id": "mirrorflix", "name": "MirrorFlix", "kind": "video mirror"},
                {"id": "streambox", "name": "StreamBox", "kind": "unauthorized retransmission"},
                {"id": "torrent-index", "name": "Torrent Index", "kind": "distribution index"},
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
                # Preserve the exact identity signed in the CDNWM4 claim. A
                # dataset selector can resolve to a concrete video file, and
                # comparing the selector with that claim would falsely reject
                # otherwise valid forensic evidence.
                "content_id": getattr(chunk, "content_id", None) or state.config.get("video_id") or default_content_id(),
                # Keep the immutable capture identity alongside the digest.
                # The monitor uses it as a second binding check before any
                # automatic administrative action is allowed.
                "watermark_id": chunk.to_dict().get("watermark_id") if hasattr(chunk, "to_dict") else getattr(chunk, "watermark_id", None),
                "watermark_algorithm": chunk.to_dict().get("watermark_algorithm") if hasattr(chunk, "to_dict") else getattr(chunk, "watermark_algorithm", None),
                "content": None,
                "created_at": time.time(),
                "capture_started_at": capture_started_at,
                "processed": False,
                "analyzed": False,
                "attributed": False,
                "forensic_state": "awaiting_analysis",
                "needs_reanalysis": False,
                "analysis_count": 0,
                "capture_completed_at": time.time(),
                "capture_duration_ms": round((time.time() - capture_started_at) * 1000.0, 3),
                "piracy_detection_probability": getattr(client, "piracy_detection_probability", 1.0),
            }
            self._repository.append_leak(leak)
            self._repository.append_event({
                "type": "piracy_published",
                "at": time.time(),
                "client_id": client.client_id,
                "leak_id": leak_id,
                "platform": platform["name"],
                "watermark_proof": "embedded-qim3",
            })
            if self._on_leak:
                self._on_leak(leak)
        except (PermissionError, RuntimeError, OSError):
            self._release_quarantine(client.client_id, "evidence capture failed")
        finally:
            state.forensic_capture_pending_clients.discard(client_id)
