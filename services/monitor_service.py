from __future__ import annotations

import threading
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from repositories.in_memory import SimulationRepository
from services.blacklist_service import BlacklistService
from services.forensic_investigation_service import ForensicInvestigationService
from services.watermark_service import WatermarkService


class MonitorService:
    """Runs one independent monitor loop for each CDN server."""

    def __init__(self, repository: SimulationRepository, watermark_service: WatermarkService, blacklist_service: BlacklistService) -> None:
        self._repository = repository
        self._watermark_service = watermark_service
        self._blacklist_service = blacklist_service
        self._investigations = ForensicInvestigationService(watermark_service)
        self._tick_interval_seconds = 1.0
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_events: Dict[str, threading.Event] = {}
        self._wake_events: Dict[str, threading.Event] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._last_results: Dict[str, Dict[str, Any]] = {}
        self._lifecycle_lock = threading.RLock()

    def start(self, servers: list[dict] | None = None, tick_interval_seconds: float = 1.0) -> None:
        self.stop()
        # The per-server lock keeps forensic extraction non-overlapping. A
        # short polling cadence only reduces the time a fresh leak waits for
        # its first authenticated inspection; it does not relax detection.
        self._tick_interval_seconds = max(1.0, float(tick_interval_seconds))
        state = self._repository.state_ref()
        candidates = servers or [server.to_dict() for server in state.servers.values()]
        for server in candidates:
            if server.get("process_mode", "http") == "virtual":
                continue
            self.add_server(str(server.get("server_id")), start_thread=server.get("status", "healthy") != "offline")

    def add_server(self, server: dict | str, tick_interval_seconds: float | None = None, start_thread: bool = True) -> None:
        server_id = str(server.get("server_id")) if isinstance(server, dict) else str(server)
        if not server_id:
            return
        if isinstance(server, dict) and server.get("process_mode", "http") == "virtual":
            return
        if tick_interval_seconds is not None:
            self._tick_interval_seconds = max(1.0, float(tick_interval_seconds))
        with self._lifecycle_lock:
            if server_id in self._threads and self._threads[server_id].is_alive():
                return
            self._locks.setdefault(server_id, threading.Lock())
            self._last_results.setdefault(server_id, {})
            if not start_thread:
                return
            stop_event = threading.Event()
            wake_event = threading.Event()
            self._stop_events[server_id] = stop_event
            self._wake_events[server_id] = wake_event
            thread = threading.Thread(target=self._run, args=(server_id, stop_event, wake_event), name=f"monitor-{server_id}", daemon=True)
            self._threads[server_id] = thread
            thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            events = list(self._stop_events.values())
            wake_events = list(self._wake_events.values())
            threads = list(self._threads.values())
            for stop_event in events:
                stop_event.set()
            for wake_event in wake_events:
                wake_event.set()
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
        with self._lifecycle_lock:
            self._threads.clear()
            self._stop_events.clear()
            self._wake_events.clear()
            self._locks.clear()
            self._last_results.clear()

    def configure_tick_interval(self, tick_interval_seconds: float) -> None:
        self._tick_interval_seconds = max(1.0, float(tick_interval_seconds))

    def remove_server(self, server_id: str) -> None:
        """Stop only the monitor owned by a server removed during live resize."""
        server_id = str(server_id)
        with self._lifecycle_lock:
            stop_event = self._stop_events.pop(server_id, None)
            wake_event = self._wake_events.pop(server_id, None)
            thread = self._threads.pop(server_id, None)
            self._locks.pop(server_id, None)
            self._last_results.pop(server_id, None)
        if stop_event:
            stop_event.set()
        if wake_event:
            wake_event.set()
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def notify_leak(self, leak: dict) -> None:
        """Start a valid forensic scan immediately instead of waiting a tick."""
        server_id = str(leak.get("server_id") or "")
        with self._lifecycle_lock:
            wake_event = self._wake_events.get(server_id)
        if wake_event:
            wake_event.set()

    def _run(self, server_id: str, stop_event: threading.Event, wake_event: threading.Event) -> None:
        while not stop_event.is_set():
            wake_event.wait(self._tick_interval_seconds)
            wake_event.clear()
            if stop_event.is_set():
                break
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
            needs_reanalysis = sum(1 for leak in state.leaks if leak.get("needs_reanalysis") and leak.get("server_id") == server_id)
            per_server[server_id] = {
                "server_id": server_id,
                "automatic": self._threads.get(server_id) is not None and self._threads[server_id].is_alive(),
                "interval_seconds": round(self._tick_interval_seconds, 2),
                "last_scan_at": result.get("scanned_at"),
                "last_scanned": result.get("scanned", 0),
                "last_detected": len(result.get("detected", [])),
                "last_rejected": len(result.get("rejected", [])),
                "pending_leaks": pending,
                "needs_reanalysis": needs_reanalysis,
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
            "needs_reanalysis": sum(item["needs_reanalysis"] for item in per_server.values()),
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

        state = self._repository.snapshot_without_clients()
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
        return {"server_id": server_id, "scanned": 0, "detected": [], "rejected": [], "blacklisted_total": len(self._repository.snapshot_without_clients().blacklist), "scanned_at": time.time(), "automatic": False}

    def _scan(self, server_id: str, automatic: bool) -> Dict[str, Any]:
        state = self._repository.state_ref()
        if automatic and (state.paused or state.lifecycle != "running"):
            return self._empty_result(server_id)
        detected: List[dict] = []
        rejected: List[dict] = []
        now = time.time()
        candidates = [
            leak for leak in list(state.leaks)
            if not leak.get("processed") and leak.get("server_id") == server_id
            and (not automatic or float(leak.get("next_analysis_at", 0)) <= now)
        ]
        for leak in candidates:
            leak["analyzed"] = True
            leak["analysis_count"] = int(leak.get("analysis_count", 0)) + 1
            leak["last_analyzed_at"] = time.time()
            try:
                media_path = leak.get("media_path")
                if media_path:
                    investigation = self._investigations.investigate_video(
                        Path(media_path), source="simulated-platform", algorithm="qim3"
                    )
                    leak["forensic_status"] = investigation["forensic_status"]
                    leak["forensic_evidence"] = investigation["evidence"]
                    leak["investigation_id"] = investigation["investigation_id"]
                    leak["investigated_media_sha256"] = investigation["media_sha256"]
                    if investigation["decision"] != "PENDING_REVIEW":
                        leak["processed"] = False
                        leak["attributed"] = False
                        leak["needs_reanalysis"] = True
                        leak["next_analysis_at"] = time.time() + 300.0
                        leak["detected_by_server_id"] = server_id
                        rejected.append({
                            "leak_id": leak.get("leak_id"),
                            "monitor_server_id": server_id,
                            "status": investigation["forensic_status"],
                            "reason": investigation["evidence"].get("reason", "evidência visual não autenticada; nenhuma ação automática"),
                        })
                        continue
                    claim = investigation["claim"]
                    leak["forensic_source"] = "visual-media"
                    # In the simulator, an exact visual marker, a valid
                    # CDNWM4 claim and a content match form a confirmed leak.
                    # Only this fully authenticated path can affect the
                    # blacklist; candidates and inconclusive media remain
                    # pending for reanalysis.
                    proof_token = self._watermark_service.registered_token_for_marker(
                        investigation["evidence"].get("marker")
                    )
                    if not proof_token:
                        raise ValueError("claim forense confirmado sem token registrado para blacklist")
                    blacklist_entry = self._blacklist_service.report(
                        proof_token,
                        reason="vazamento autenticado por QIM3/CDNWM4 e correspondência de conteúdo",
                        detected_by_server_id=server_id,
                        trace_id=str(leak.get("trace_id") or ""),
                    )
                else:
                    raise ValueError("vazamento sem mídia não permite atribuição forense")
                leak["processed"] = True
                leak["attributed"] = True
                leak["attributed_client_id"] = claim["client_id"]
                state.forensic_pending_clients.discard(str(claim["client_id"]))
                leak["needs_reanalysis"] = False
                leak["review_status"] = "PENDING_REVIEW"
                leak["detected_at"] = time.time()
                leak["detected_by_server_id"] = server_id
                detected.append({"leak_id": leak["leak_id"], "monitor_server_id": server_id, "claim": claim, "investigation_id": investigation["investigation_id"], "decision": "PENDING_REVIEW", "blacklist": blacklist_entry.to_dict(), "forensic_source": leak["forensic_source"]})
            except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                leak["processed"] = False
                leak["attributed"] = False
                leak["needs_reanalysis"] = True
                leak["next_analysis_at"] = time.time() + 300.0
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
            "proof_algorithm": "CDNWM4 / DCT-QIM3 + AES-256-GCM + HMAC-SHA256",
            "source": "embedded chunk bytes",
            "automatic": automatic,
        })
        return result

    def verify_token(self, token: str) -> dict:
        return self._watermark_service.verify(token).to_dict()
