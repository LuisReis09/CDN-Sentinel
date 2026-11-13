import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.forensic_investigation_service import ForensicInvestigationService
from services.watermark_service import WatermarkService
from services.watermark_registry import WatermarkRegistry


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

    def detect_forensic_video(self, path, *, algorithm):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class ForensicStatesTests(unittest.TestCase):
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
