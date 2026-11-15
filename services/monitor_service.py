from __future__ import annotations

import threading
import subprocess
import time
import random
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
            self.add_server(str(server.get("server_id")), start_thread=server.get("status", "healthy") != "offline")

    def add_server(self, server: dict | str, tick_interval_seconds: float | None = None, start_thread: bool = True) -> None:
        server_id = str(server.get("server_id")) if isinstance(server, dict) else str(server)
        if not server_id:
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
            if wake_event is None:
                # A monitor can disappear during a live topology change. Move
                # the analysis lease to a still-running peer while preserving
                # origin_server_id for the watermark binding. Virtual servers
                # also own controller-side monitor loops, so they only reach
                # this branch after that loop was actually removed.
                for candidate_id, candidate_event in self._wake_events.items():
                    if candidate_id in self._threads and self._threads[candidate_id].is_alive():
                        leak["server_id"] = candidate_id
                        leak["analysis_owner_server_id"] = candidate_id
                        wake_event = candidate_event
                        self._repository.append_event({
                            "type": "forensic_analysis_reassigned",
                            "at": time.time(),
                            "leak_id": leak.get("leak_id"),
                            "from_server_id": server_id,
                            "to_server_id": candidate_id,
                            "reason": "monitor owner unavailable during topology change",
                        })
                        break
        if wake_event:
            wake_event.set()
        else:
            # Small/fully-virtual simulations have no monitor threads; run a
            # bounded scan inline so a captured client cannot remain blocked.
            try:
                self.scan(server_id=server_id, automatic=True)
            except RuntimeError:
                pass

    def quarantine_client(self, client_id: str) -> dict:
        return self._blacklist_service.quarantine(client_id)

    def release_quarantine(self, client_id: str, reason: str) -> None:
        if self._blacklist_service:
            self._blacklist_service.release_quarantine(client_id, reason)

    def maintain_quarantines(self) -> list[dict]:
        """Transfer live investigations away from a failed analysis node."""
        if not self._blacklist_service:
            return []
        actions = self._blacklist_service.maintain_quarantines()
        if not actions:
            return actions
        state = self._repository.state_ref()
        for action in actions:
            if action.get("action") != "reassigned":
                continue
            client_id = action["client_id"]
            replacement = action["server_id"]
            for leak in state.leaks:
                if leak.get("client_id") == client_id and not leak.get("processed"):
                    leak["server_id"] = replacement
                    leak["analysis_owner_server_id"] = replacement
                    self.notify_leak(leak)
        return actions

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

    def _retry_policy(self, state, leak: dict) -> tuple[int, float, bool]:
        profile = str(state.config.get("simulation_profile", "realistic"))
        max_attempts = max(1, int(state.config.get("forensic_max_attempts", 4)))
        configured_base = float(state.config.get("forensic_retry_base_seconds", 1.5))
        base = min(configured_base, 0.5) if profile == "fast" else configured_base
        attempt = int(leak.get("analysis_count", 0))
        exhausted = attempt >= max_attempts
        return max_attempts, min(30.0, max(0.25, base) * (2 ** max(0, attempt - 1))), exhausted

    def _mark_inconclusive(self, state, leak: dict, server_id: str, *, status: str, reason: str, error: str | None = None) -> bool:
        """Schedule bounded retry while keeping the client's temporary block."""
        max_attempts, retry_delay, exhausted = self._retry_policy(state, leak)
        now = time.time()
        leak["processed"] = bool(exhausted)
        leak["attributed"] = False
        leak["forensic_state"] = "error" if status == "ERROR" else "inconclusive"
        leak["forensic_status"] = status
        leak["needs_reanalysis"] = not exhausted
        leak["next_analysis_at"] = now + retry_delay if not exhausted else None
        leak["detected_by_server_id"] = server_id
        leak["analysis_last_reason"] = reason
        leak["analysis_max_attempts"] = max_attempts
        leak["analysis_exhausted"] = exhausted
        if error:
            leak["error"] = error
        client_id = str(leak.get("client_id") or "")
        if exhausted:
            leak["review_status"] = "EXHAUSTED"
            self.release_quarantine(client_id, "forensic retries exhausted")
        else:
            leak["review_status"] = "RETRY_PENDING"
            if self._blacklist_service:
                self._blacklist_service.renew_quarantine(client_id, f"forensic retry {leak.get('analysis_count', 0)}/{max_attempts}")
        return exhausted

    def _detection_pass(self, state, leak: dict) -> bool:
        """Model the monitor's chance of surfacing a published leak.

        Detection probability only decides whether this scan sees the leak;
        it never creates a blacklist entry.  A later retry can still inspect
        the exact captured bytes, so a permanent ban remains contingent on
        authentic watermark evidence.
        """
        # A LeakService record is already the monitor's discovery event: it
        # represents a sample found on an external simulated platform.  Do
        # not introduce another lottery after discovery, or short runs may
        # never inspect an otherwise authentic copy.  The watermark/digest
        # investigation below remains mandatory before any blacklist action.
        if all((
            leak.get("media_path"),
            leak.get("media_sha256"),
            leak.get("client_id"),
            leak.get("origin_server_id"),
            leak.get("content_id"),
        )):
            return True
        probability = float(leak.get("piracy_detection_probability", 1.0) or 0.0)
        probability = max(0.0, min(1.0, probability))
        if probability >= 1.0:
            return True
        sample = random.Random(
            f"{state.config.get('seed', 2026)}:{leak.get('leak_id')}:{leak.get('analysis_count', 0)}"
        ).random()
        if sample <= probability:
            return True
        self._repository.append_event({
            "type": "piracy_detection_deferred",
            "at": time.time(),
            "leak_id": leak.get("leak_id"),
            "client_id": leak.get("client_id"),
            "detection_probability": probability,
            "attempt": leak.get("analysis_count", 0),
            "reason": "monitor probabilistic scheduling; no forensic verdict yet",
        })
        return False

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
            analysis_started = time.time()
            leak["last_analyzed_at"] = analysis_started
            leak["forensic_state"] = "processing"
            try:
                if not self._detection_pass(state, leak):
                    exhausted = self._mark_inconclusive(
                        state,
                        leak,
                        server_id,
                        status="INCONCLUSIVE",
                        reason="detection window did not surface the published leak",
                    )
                    rejected.append({
                        "leak_id": leak.get("leak_id"),
                        "monitor_server_id": server_id,
                        "status": "INCONCLUSIVE",
                        "reason": "detection window did not surface the published leak",
                        "retry_scheduled": not exhausted,
                        "attempt": leak["analysis_count"],
                    })
                    continue
                media_path = leak.get("media_path")
                if media_path:
                    # Only the leak worker can supply every immutable capture
                    # binding.  Manually submitted or external/re-encoded
                    # evidence keeps the complete Studio-grade content match.
                    if all((
                        leak.get("media_sha256"),
                        leak.get("client_id"),
                        leak.get("origin_server_id"),
                        leak.get("content_id"),
                    )):
                        investigation = self._investigations.investigate_simulated_cdn_leak(
                            Path(media_path),
                            expected_media_sha256=str(leak["media_sha256"]),
                            expected_client_id=str(leak["client_id"]),
                            expected_server_id=str(leak["origin_server_id"]),
                            expected_content_id=str(leak["content_id"]),
                            algorithm="qim3",
                        )
                    else:
                        investigation = self._investigations.investigate_video(
                            Path(media_path), source="simulated-platform", algorithm="qim3"
                        )
                    leak["forensic_status"] = investigation["forensic_status"]
                    leak["forensic_evidence"] = investigation["evidence"]
                    leak["investigation_id"] = investigation["investigation_id"]
                    leak["investigated_media_sha256"] = investigation["media_sha256"]
                    if investigation["decision"] != "PENDING_REVIEW":
                        leak["analysis_duration_ms"] = round((time.time() - analysis_started) * 1000.0, 3)
                        exhausted = self._mark_inconclusive(
                            state,
                            leak,
                            server_id,
                            status=str(investigation.get("forensic_status") or "INCONCLUSIVE"),
                            reason=str(investigation.get("evidence", {}).get("reason", "visual evidence not authenticated")),
                        )
                        rejected.append({
                            "leak_id": leak.get("leak_id"),
                            "monitor_server_id": server_id,
                            "status": investigation["forensic_status"],
                            "reason": investigation["evidence"].get("reason", "evidência visual não autenticada; nenhuma ação automática"),
                        })
                        rejected[-1]["retry_scheduled"] = not exhausted
                        rejected[-1]["attempt"] = leak["analysis_count"]
                        continue
                    claim = investigation["claim"]
                    leak["forensic_source"] = "visual-media"
                    simulated_capture = all((
                        leak.get("media_sha256"),
                        leak.get("client_id"),
                        leak.get("origin_server_id"),
                        leak.get("content_id"),
                    ))
                    if simulated_capture:
                        # A simulator capture is only eligible for automatic
                        # action when every identity binding agrees.  The
                        # client flag is an invariant of this path: LeakService
                        # selects only clients explicitly classified as
                        # malicious.  If a valid marker points at a regular
                        # client, the record is inconsistent (or stale), not
                        # proof of piracy.  Never turn that inconsistency into
                        # a permanent ban.
                        expected_client_id = str(leak.get("client_id"))
                        expected_server_id = str(leak.get("origin_server_id"))
                        claim_client_id = str(claim.get("client_id") or "")
                        claim_server_id = str(claim.get("server_id") or "")
                        bound_client = state.clients.get(claim_client_id)
                        expected_watermark_id = str(leak.get("watermark_id") or "")
                        claim_watermark_id = str(claim.get("watermark_id") or "")
                        expected_algorithm = str(leak.get("watermark_algorithm") or "")
                        claim_algorithm = str(claim.get("algorithm_id") or "")
                        if (
                            claim_client_id != expected_client_id
                            or claim_server_id != expected_server_id
                            or (expected_watermark_id and claim_watermark_id != expected_watermark_id)
                            or (expected_algorithm and claim_algorithm != expected_algorithm)
                            or bound_client is None
                            or not bound_client.malicious
                        ):
                            reason = "vínculo forense rejeitado: claim não corresponde ao cliente malicioso capturado"
                            leak["forensic_status"] = "INCONCLUSIVE"
                            leak["forensic_state"] = "inconclusive"
                            leak["processed"] = True
                            leak["attributed"] = False
                            leak["needs_reanalysis"] = False
                            leak["review_status"] = "REJECTED_BINDING"
                            leak["analysis_last_reason"] = reason
                            leak["detected_by_server_id"] = server_id
                            leak["analysis_duration_ms"] = round((time.time() - analysis_started) * 1000.0, 3)
                            self.release_quarantine(expected_client_id, "forensic claim binding rejected")
                            rejected.append({
                                "leak_id": leak.get("leak_id"),
                                "monitor_server_id": server_id,
                                "status": "INCONCLUSIVE",
                                "reason": reason,
                                "retry_scheduled": False,
                                "attempt": leak["analysis_count"],
                            })
                            continue
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
                        reason="vazamento autenticado por QIM3/CDNWM4 e vínculo íntegro da entrega simulada",
                        detected_by_server_id=server_id,
                        trace_id=str(leak.get("trace_id") or ""),
                    )
                else:
                    raise ValueError("vazamento sem mídia não permite atribuição forense")
                leak["processed"] = True
                leak["attributed"] = True
                leak["forensic_state"] = "confirmed"
                leak["analysis_duration_ms"] = round((time.time() - analysis_started) * 1000.0, 3)
                leak["attributed_client_id"] = claim["client_id"]
                state.forensic_pending_clients.discard(str(claim["client_id"]))
                leak["needs_reanalysis"] = False
                leak["review_status"] = "PENDING_REVIEW"
                leak["detected_at"] = time.time()
                leak["detected_by_server_id"] = server_id
                self.release_quarantine(str(leak.get("client_id") or ""), "permanent blacklist installed")
                detected.append({"leak_id": leak["leak_id"], "monitor_server_id": server_id, "claim": claim, "investigation_id": investigation["investigation_id"], "decision": "PENDING_REVIEW", "blacklist": blacklist_entry.to_dict(), "forensic_source": leak["forensic_source"]})
            except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                leak["analysis_duration_ms"] = round((time.time() - analysis_started) * 1000.0, 3)
                exhausted = self._mark_inconclusive(
                    state,
                    leak,
                    server_id,
                    status="ERROR",
                    reason="forensic processing failed",
                    error=str(exc),
                )
                rejected.append({"leak_id": leak.get("leak_id"), "monitor_server_id": server_id, "error": str(exc), "retry_scheduled": not exhausted, "attempt": leak["analysis_count"]})
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
