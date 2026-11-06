from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from repositories.in_memory import SimulationRepository
from services.blacklist_service import BlacklistService
from services.watermark_service import WatermarkService
from utils.video import extract_watermark_token


class MonitorService:
    """Runs one independent monitor loop for each CDN server."""

    def __init__(self, repository: SimulationRepository, watermark_service: WatermarkService, blacklist_service: BlacklistService) -> None:
        self._repository = repository
        self._watermark_service = watermark_service
        self._blacklist_service = blacklist_service
        self._tick_interval_seconds = 2.5
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_events: Dict[str, threading.Event] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._last_results: Dict[str, Dict[str, Any]] = {}
        self._lifecycle_lock = threading.RLock()

    def start(self, servers: list[dict] | None = None, tick_interval_seconds: float = 2.5) -> None:
        self.stop()
        self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))
        state = self._repository.state_ref()
        candidates = servers or [server.to_dict() for server in state.servers.values()]
        for server in candidates:
            self.add_server(str(server.get("server_id")), start_thread=server.get("status", "healthy") != "offline")

    def add_server(self, server: dict | str, tick_interval_seconds: float | None = None, start_thread: bool = True) -> None:
        server_id = str(server.get("server_id")) if isinstance(server, dict) else str(server)
        if not server_id:
            return
        if tick_interval_seconds is not None:
            self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))
        with self._lifecycle_lock:
            if server_id in self._threads and self._threads[server_id].is_alive():
                return
            self._locks.setdefault(server_id, threading.Lock())
            self._last_results.setdefault(server_id, {})
            if not start_thread:
                return
            stop_event = threading.Event()
            self._stop_events[server_id] = stop_event
            thread = threading.Thread(target=self._run, args=(server_id, stop_event), name=f"monitor-{server_id}", daemon=True)
            self._threads[server_id] = thread
            thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            events = list(self._stop_events.values())
            threads = list(self._threads.values())
            for stop_event in events:
                stop_event.set()
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
        with self._lifecycle_lock:
            self._threads.clear()
            self._stop_events.clear()
            self._locks.clear()
            self._last_results.clear()

    def configure_tick_interval(self, tick_interval_seconds: float) -> None:
        self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))

    def _run(self, server_id: str, stop_event: threading.Event) -> None:
        while not stop_event.wait(self._tick_interval_seconds):
            try:
                self.scan(server_id=server_id, automatic=True)
            except RuntimeError:
                continue

    def status(self) -> dict:
        state = self._repository.state_ref()
        server_ids = sorted({*state.servers.keys(), *self._last_results.keys()})
        per_server: dict[str, dict] = {}
        for server_id in server_ids:
            result = self._last_results.get(server_id, {})
            pending = sum(1 for leak in state.leaks if not leak.get("processed") and leak.get("server_id") == server_id)
            per_server[server_id] = {
                "server_id": server_id,
                "automatic": self._threads.get(server_id) is not None and self._threads[server_id].is_alive(),
                "interval_seconds": round(self._tick_interval_seconds, 2),
                "last_scan_at": result.get("scanned_at"),
                "last_scanned": result.get("scanned", 0),
                "last_detected": len(result.get("detected", [])),
                "last_rejected": len(result.get("rejected", [])),
                "pending_leaks": pending,
            }
        result_times = [item["last_scan_at"] for item in per_server.values() if item["last_scan_at"]]
        return {
            "automatic": any(item["automatic"] for item in per_server.values()),
            "interval_seconds": round(self._tick_interval_seconds, 2),
            "last_scan_at": max(result_times) if result_times else None,
            "last_scanned": sum(item["last_scanned"] for item in per_server.values()),
            "last_detected": sum(item["last_detected"] for item in per_server.values()),
            "last_rejected": sum(item["last_rejected"] for item in per_server.values()),
            "pending_leaks": sum(item["pending_leaks"] for item in per_server.values()),
            "per_server": per_server,
        }

    def scan(self, server_id: str | None = None, automatic: bool = False) -> Dict[str, Any]:
        if server_id:
            lock = self._locks.setdefault(server_id, threading.Lock())
            if not lock.acquire(blocking=False):
                return self._last_results.get(server_id, self._empty_result(server_id))
            try:
                return self._scan(server_id, automatic)
            finally:
                lock.release()

        state = self._repository.snapshot()
        results = [self.scan(server_id=current_id, automatic=automatic) for current_id in state.servers]
        return {
            "server_id": "all",
            "scanned": sum(result.get("scanned", 0) for result in results),
            "detected": [item for result in results for item in result.get("detected", [])],
            "rejected": [item for result in results for item in result.get("rejected", [])],
            "blacklisted_total": len(state.blacklist),
            "scanned_at": time.time(),
            "automatic": automatic,
        }

    def _empty_result(self, server_id: str) -> dict:
        return {"server_id": server_id, "scanned": 0, "detected": [], "rejected": [], "blacklisted_total": len(self._repository.snapshot().blacklist), "scanned_at": time.time(), "automatic": False}

    def _scan(self, server_id: str, automatic: bool) -> Dict[str, Any]:
        state = self._repository.state_ref()
        detected: List[dict] = []
        rejected: List[dict] = []
        candidates = [leak for leak in list(state.leaks) if not leak.get("processed") and leak.get("server_id") == server_id]
        for leak in candidates:
            try:
                token = extract_watermark_token(leak.get("content", ""))
                claim = self._watermark_service.verify(token)
                entry = self._blacklist_service.report(token, detected_by_server_id=server_id, trace_id=leak.get("trace_id"))
                leak["processed"] = True
                leak["detected_at"] = time.time()
                leak["detected_by_server_id"] = server_id
                detected.append({"leak_id": leak["leak_id"], "monitor_server_id": server_id, "claim": claim.to_dict(), "blacklist": entry.to_dict()})
            except (ValueError, KeyError, TypeError) as exc:
                leak["processed"] = True
                leak["error"] = str(exc)
                leak["detected_by_server_id"] = server_id
                rejected.append({"leak_id": leak.get("leak_id"), "monitor_server_id": server_id, "error": str(exc)})
        result = {
            "server_id": server_id,
            "scanned": len(candidates),
            "detected": detected,
            "rejected": rejected,
            "blacklisted_total": len(state.blacklist),
            "scanned_at": time.time(),
            "automatic": automatic,
            "trace_id": candidates[0].get("trace_id") if candidates else None,
        }
        self._last_results[server_id] = result
        state.scan_history.append(result)
        state.scan_history = state.scan_history[-500:]
        self._repository.append_event({
            "type": "monitor_scan",
            "at": result["scanned_at"],
            "server_id": server_id,
            "monitor_server_id": server_id,
            "detected": len(detected),
            "rejected": len(rejected),
            "proof_algorithm": "HMAC-SHA256",
            "source": "embedded chunk bytes",
            "automatic": automatic,
        })
        return result

    def verify_token(self, token: str) -> dict:
        return self._watermark_service.verify(token).to_dict()
