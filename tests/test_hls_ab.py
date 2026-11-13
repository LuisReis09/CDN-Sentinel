import subprocess
import tempfile
import unittest
from pathlib import Path

from media.hls_ab import HLSABService
from services.watermark_registry import WatermarkRegistry
from services.watermark_service import WatermarkService


class _LocalProvider:
    def __init__(self, source: Path) -> None:
        self.source = source

    def resolve_asset(self, content_id: str, chunk_number: int = 0):
        if content_id != "synthetic":
            raise KeyError(content_id)
        return self.source, "video/mp4"

    def get_chunk(self, content_id: str, chunk_number: int):
        return self.source.read_bytes(), "video/mp4"


class HLSABTests(unittest.TestCase):
    def test_preencoded_segments_and_unique_session_playlists(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x128:rate=10:duration=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=22050:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
            ], check=True, capture_output=True, timeout=60)
            registry = WatermarkRegistry(root / "ledger.sqlite3")
            service = WatermarkService("hls-test-secret-with-entropy", registry)
            hls = HLSABService(service, _LocalProvider(source), cache_root=root / "cache", segment_seconds=1)
            # Reserve the fixed viewer identity first. A three-bit A/B clip
            # has only eight possible patterns; reserving it after random
            # sessions makes this compatibility test probabilistic.
            bound = hls.create_session("client-c", "edge-a", "synthetic", viewer_session_id="view-test-session-123")
            self.assertEqual(bound["session_id"], "view-test-session-123")
            self.assertEqual(hls.create_session("client-c", "edge-a", "synthetic", viewer_session_id="view-test-session-123")["session_id"], bound["session_id"])
            with self.assertRaises(PermissionError):
                hls.create_session("client-d", "edge-a", "synthetic", viewer_session_id="view-test-session-123")
            first = hls.create_session("client-a", "edge-a", "synthetic")
            second = hls.create_session("client-b", "edge-a", "synthetic")
            self.assertEqual(first["segments"], 3)
            self.assertTrue(second["cache_hit"])
            self.assertNotEqual(first["session_id"], second["session_id"])
            first_record = registry.ab_session(service.secret_key, first["session_id"])
            second_record = registry.ab_session(service.secret_key, second["session_id"])
            self.assertNotEqual(first_record["fingerprint"], second_record["fingerprint"])
            self.assertIn("#EXT-X-ENDLIST", hls.manifest(first["session_id"], "client-a"))
            self.assertFalse(first["attribution_ready"])
            self.assertEqual(first["watermark_algorithm"], "dct-qim-v3")
            self.assertEqual(len(list((root / "cache" / hls.prepare("synthetic")["cache_id"] / "A").glob("*.ts"))), 3)
            for index in range(3):
                segment = hls.segment(first["session_id"], "client-a", index)
                result = subprocess.run([
                    "ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(segment),
                ], check=True, capture_output=True, text=True, timeout=30)
                self.assertIn("h264", result.stdout)
                self.assertIn("aac", result.stdout)
            analysis = hls.analyze_segments("synthetic", [hls.segment(first["session_id"], "client-a", index) for index in range(3)])
            self.assertEqual(analysis["status"], "INCONCLUSIVE")
            self.assertNotEqual(analysis.get("attribution"), "AUTHENTICATED_SESSION")
            with self.assertRaises(KeyError):
                hls.segment(first["session_id"], "client-b", 0)


if __name__ == "__main__":
    unittest.main()
