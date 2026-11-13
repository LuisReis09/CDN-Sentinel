"""Full Studio path using real media, claim ledger, extraction and content gate."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import create_app
from services.content_provider import DatasetContentProvider


class ForensicStudioE2ETests(unittest.TestCase):
    def test_studio_issues_and_investigates_real_qim3_media(self):
        with tempfile.TemporaryDirectory(prefix="cdn-studio-ledger-") as directory:
            previous = os.environ.get("CDN_WATERMARK_REGISTRY_PATH")
            os.environ["CDN_WATERMARK_REGISTRY_PATH"] = str(Path(directory) / "ledger.sqlite3")
            try:
                client = create_app().test_client()
                response = client.post("/api/security/watermark/demo/forensic", json={"video_id": "bigbuckbunny", "algorithm": "qim3"})
                self.assertEqual(response.status_code, 200, response.get_json())
                body = response.get_json()
                self.assertEqual(body["pipeline"], "CDNWM4")
                if DatasetContentProvider().available():
                    self.assertTrue(body["video_id"].startswith("youtube_clipped_videos/"), body["video_id"])
                else:
                    self.assertEqual(body["video_id"], "bigbuckbunny")
                self.assertEqual(body["claim"]["version"], "CDNWM4")
                self.assertEqual(body["visual_detection"]["marker"], body["issued_marker"])
                self.assertEqual(body["ledger_status"], "VALID")
                self.assertEqual(body["investigation"]["decision"], "PENDING_REVIEW")
                self.assertEqual(body["investigation"]["content_match"]["status"], "MATCH")
                self.assertTrue(body["video_alignment"]["aligned"])
                for variant, url in body["video_variants"].items():
                    asset = client.get(url)
                    self.assertEqual(asset.status_code, 200, variant)
                    self.assertTrue(asset.data.startswith(b"\x89PNG" if variant == "detection_map" else b"\x00\x00"), variant)
                    if variant == "difference":
                        difference_path = Path(directory) / "difference.mp4"
                        difference_path.write_bytes(asset.data)
                        frame = subprocess.run(
                            ["ffmpeg", "-v", "error", "-i", str(difference_path), "-frames:v", "1",
                             "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
                            check=True, capture_output=True, timeout=30,
                        ).stdout
                        self.assertGreater(sum(frame) / len(frame), 3.0)
            finally:
                if previous is None:
                    os.environ.pop("CDN_WATERMARK_REGISTRY_PATH", None)
                else:
                    os.environ["CDN_WATERMARK_REGISTRY_PATH"] = previous
