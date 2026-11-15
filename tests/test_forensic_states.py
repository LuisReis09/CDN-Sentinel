import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch

from models.entities import CDNServer, Client, SimulationState
from repositories.in_memory import SimulationRepository
from services.forensic_investigation_service import ForensicInvestigationService
from services.blacklist_service import BlacklistService
from services.cdn_http_client import CDNHttpClient
from services.monitor_service import MonitorService
from services.watermark_service import WatermarkService
from services.watermark_registry import WatermarkRegistry
from utils.image_watermark import visual_marker


class FakeRegistry:
    def __init__(self):
        self.events = []

    def append_forensic_event(self, secret, event_type, payload, watermark_id):
        event = {"event_type": event_type, "payload": payload, "watermark_id": watermark_id}
        self.events.append(event)
        return event

    def verify_forensic_events(self, secret):
        return True

    def forensic_events(self, secret):
        return self.events


class FakeWatermarkService:
    secret_key = "test-secret"

    def __init__(self, result):
        self.result = result
        self._registry_store = FakeRegistry()
        self.calls = []

    def detect_forensic_video(self, path, *, algorithm, **kwargs):
        self.calls.append({"path": path, "algorithm": algorithm, **kwargs})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class ForensicStatesTests(unittest.TestCase):
    def test_simulated_capture_for_regular_client_is_rejected_without_blacklist(self):
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary) / "capture.mp4"
            media.write_bytes(b"capture")
            client = Client("regular", 0, 0, "Test", malicious=False)
            server = CDNServer("edge-a", "127.0.0.1", 5101, 0, 0, "A", status="healthy", process_mode="virtual")
            repository = SimulationRepository()
            repository.replace(SimulationState(
                initialized=True,
                lifecycle="running",
                config={"seed": 7},
                clients={client.client_id: client},
                servers={server.server_id: server},
                leaks=[{
                    "leak_id": "capture-regular",
                    "server_id": server.server_id,
                    "origin_server_id": server.server_id,
                    "client_id": client.client_id,
                    "content_id": "movie-a",
                    "media_path": str(media),
                    "media_sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
                    "watermark_id": "wm-regular",
                    "processed": False,
                }],
            ))
            watermark = FakeWatermarkService({})
            blacklist = BlacklistService(repository, CDNHttpClient(), watermark)
            monitor = MonitorService(repository, watermark, blacklist)
            claim = {
                "client_id": client.client_id,
                "server_id": server.server_id,
                "content_id": "movie-a",
                "watermark_id": "wm-regular",
            }
            with patch.object(monitor._investigations, "investigate_simulated_cdn_leak", return_value={
                "forensic_status": "VALID",
                "decision": "PENDING_REVIEW",
                "claim": claim,
                "evidence": {"marker": "registered-marker"},
                "investigation_id": "inv-regular",
                "media_sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
            }):
                result = monitor.scan(server.server_id)

            self.assertEqual(result["detected"], [])
            self.assertEqual(len(repository.blacklist_values()), 0)
            stored = repository.state_ref().leaks[0]
            self.assertTrue(stored["processed"])
            self.assertEqual(stored["review_status"], "REJECTED_BINDING")
            self.assertFalse(stored["attributed"])

    def test_monitor_requests_only_the_current_qim3_detector(self):
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary) / "leak.mp4"
            media.write_bytes(b"test")
            repository = SimulationRepository()
            repository.replace(SimulationState(
                initialized=True,
                servers={"edge-a": CDNServer("edge-a", "127.0.0.1", 5101, 0, 0, "A")},
                leaks=[{"leak_id": "leak-a", "server_id": "edge-a", "media_path": str(media), "processed": False}],
            ))
            service = WatermarkService("monitor-current-secret-2026", WatermarkRegistry(Path(temporary) / "ledger.sqlite3"))
            monitor = MonitorService(repository, service, None)
            with patch.object(monitor._investigations, "investigate_video", return_value={
                "forensic_status": "NOT_FOUND", "decision": "NOT_FOUND", "evidence": {"reason": "not_found"}
            }) as investigate:
                result = monitor.scan("edge-a")
            self.assertEqual(result["scanned"], 1)
            self.assertEqual(investigate.call_args.kwargs["algorithm"], "qim3")

    def test_simulated_cdn_fast_path_still_requires_watermark_and_capture_bindings(self):
        claim = {
            "client_id": "client-a",
            "server_id": "edge-a",
            "content_id": "movie-a",
            "session_id": "session-a",
            "watermark_id": "watermark-a",
        }
        service = FakeWatermarkService({"forensic_status": "VALID", "claim": claim})
        investigator = ForensicInvestigationService(service)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.mp4"
            path.write_bytes(b"simulated-media")
            digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            result = investigator.investigate_simulated_cdn_leak(
                path,
                expected_media_sha256=digest,
                expected_client_id="client-a",
                expected_server_id="edge-a",
                expected_content_id="movie-a",
            )
            self.assertEqual(result["decision"], "PENDING_REVIEW")
            mismatch = investigator.investigate_simulated_cdn_leak(
                path,
                expected_media_sha256="0" * 64,
                expected_client_id="client-a",
                expected_server_id="edge-a",
                expected_content_id="movie-a",
            )
        self.assertEqual(mismatch["decision"], "INCONCLUSIVE")
        self.assertFalse(mismatch["content_match"]["bindings"]["digest"])
        self.assertTrue(all(call["max_frames"] == 6 for call in service.calls))
        self.assertTrue(all(call["sample_interval_seconds"] == 0.5 for call in service.calls))
        self.assertTrue(all(call["qim3_soft_decode"] for call in service.calls))

    def test_simulated_forensic_plan_requires_exact_registered_marker_after_soft_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = WatermarkService(
                "simulated-evidence-plan-secret-2026",
                WatermarkRegistry(Path(temporary) / "ledger.sqlite3"),
            )
            token, _claim = service.issue_forensic_claim(
                client_id="client-a",
                server_id="edge-a",
                content_id="movie-a",
                algorithm_id="dct-qim-v3",
            )
            marker = visual_marker(token)
            with patch("services.watermark_service.detect_video", return_value={
                "status": "CANDIDATE", "marker": marker, "frame_support": 0.8,
            }) as detector:
                result = service.detect_forensic_video(
                    "captured.mp4",
                    algorithm="qim3",
                    max_frames=6,
                    sample_interval_seconds=0.5,
                    qim3_soft_decode=True,
                )
            self.assertEqual(result["forensic_status"], "VALID")
            self.assertEqual(detector.call_args.kwargs["sample_interval_seconds"], 0.5)
            self.assertTrue(detector.call_args.kwargs["qim3_soft_decode"])

            # A soft-decoded marker with no exact ledger entry remains
            # non-attributable; the recovery setting cannot create a ban.
            with patch("services.watermark_service.detect_video", return_value={
                "status": "CANDIDATE", "marker": "000000000000", "frame_support": 1.0,
            }):
                unknown = service.detect_forensic_video(
                    "captured.mp4",
                    algorithm="qim3",
                    max_frames=6,
                    sample_interval_seconds=0.5,
                    qim3_soft_decode=True,
                )
            self.assertEqual(unknown["forensic_status"], "CANDIDATE")

    def test_virtual_server_gets_continuous_monitor_loop(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = SimulationRepository()
            server = CDNServer("virtual-a", "127.0.0.1", 5101, 0, 0, "A", status="healthy", process_mode="virtual")
            repository.replace(SimulationState(initialized=True, lifecycle="running", servers={server.server_id: server}))
            watermark = WatermarkService(
                "virtual-monitor-secret-2026",
                WatermarkRegistry(Path(temporary) / "ledger.sqlite3"),
            )
            monitor = MonitorService(repository, watermark, BlacklistService(repository, CDNHttpClient(), watermark))
            try:
                monitor.start([server.to_dict()], tick_interval_seconds=1.0)
                self.assertTrue(monitor.status()["per_server"][server.server_id]["automatic"])
            finally:
                monitor.stop()

    def test_detector_prefers_inconclusive_to_not_found_and_never_maps_unknown_to_absence(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = WatermarkService("state-test-secret-with-entropy-2026", WatermarkRegistry(Path(temporary) / "ledger.sqlite3"))
            with patch("services.watermark_service.detect_video", side_effect=[
                {"status": "NOT_FOUND"}, {"status": "INCONCLUSIVE", "reason": "weak-signal"}, {"status": "NOT_FOUND"}
            ]):
                self.assertEqual(service.detect_forensic_video("unused.mp4")["forensic_status"], "INCONCLUSIVE")
            with patch("services.watermark_service.detect_video", return_value={"status": "DECODE_FAILED"}):
                self.assertEqual(service.detect_forensic_video("unused.mp4")["forensic_status"], "ERROR")

    def test_detector_states_are_distinct_and_raw_result_is_preserved(self):
        cases = (
            ({"forensic_status": "NOT_FOUND", "scores": [0.1]}, "NOT_FOUND"),
            ({"forensic_status": "INCONCLUSIVE", "reason": "low-confidence"}, "INCONCLUSIVE"),
            ({"forensic_status": "CANDIDATE", "marker": "0123456789ab"}, "CANDIDATE"),
            ({"forensic_status": "DECODE_FAILED"}, "ERROR"),
            (RuntimeError("decoder failed"), "ERROR"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.mp4"
            path.write_bytes(b"test")
            for detector_result, expected in cases:
                with self.subTest(expected=expected, detector_result=detector_result):
                    service = FakeWatermarkService(detector_result)
                    result = ForensicInvestigationService(service).investigate_video(path)
                    self.assertEqual(result["decision"], expected)
                    self.assertEqual(result["attribution"], "NONE")
                    self.assertEqual(result["evidence"], service._registry_store.events[0]["payload"]["detector_result"])
                    if isinstance(detector_result, dict):
                        self.assertEqual(result["evidence"], detector_result)

    def test_authenticated_match_requires_review_and_review_records_identity(self):
        claim = {"content_id": "movie-a", "session_id": "session-a", "watermark_id": "watermark-a"}
        service = FakeWatermarkService({"forensic_status": "VALID", "claim": claim})
        investigator = ForensicInvestigationService(service)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.mp4"
            path.write_bytes(b"test")
            with patch.object(investigator._catalog, "resolve_asset", return_value=(path, "video")), patch(
                "services.forensic_investigation_service.match_claimed_content", return_value={"status": "MATCH"}
            ):
                result = investigator.investigate_video(path)
        self.assertEqual(result["decision"], "PENDING_REVIEW")
        self.assertEqual(result["attribution"], "AUTHENTICATED_SESSION")
        review = investigator.review(result["investigation_id"], "ACCEPT", "reviewer-a", "evidence checked")
        self.assertEqual(review["state"], "REVIEWED")
        self.assertEqual(review["reviewer"], "reviewer-a")
        with self.assertRaises(ValueError):
            investigator.review(result["investigation_id"], "ACCEPT", "reviewer-b")

    def test_content_mismatch_and_processing_failure_do_not_attribute(self):
        claim = {"content_id": "movie-a", "session_id": "session-a", "watermark_id": "watermark-a"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.mp4"
            path.write_bytes(b"test")
            for match_result, expected in (({"status": "MISMATCH"}, "INCONCLUSIVE"), ({"status": "UNKNOWN"}, "ERROR")):
                with self.subTest(match_result=match_result):
                    service = FakeWatermarkService({"forensic_status": "VALID", "claim": claim})
                    investigator = ForensicInvestigationService(service)
                    with patch.object(investigator._catalog, "resolve_asset", return_value=(path, "video")), patch(
                        "services.forensic_investigation_service.match_claimed_content", return_value=match_result
                    ):
                        result = investigator.investigate_video(path)
                    self.assertEqual(result["decision"], expected)
                    self.assertEqual(result["attribution"], "NONE")


if __name__ == "__main__":
    unittest.main()
