import subprocess
import tempfile
import unittest
from pathlib import Path

from watermark.content_match import match_claimed_content


class ContentMatchTests(unittest.TestCase):
    def test_reencoded_reference_matches_and_unrelated_video_does_not(self):
        reference = Path("data/media/bigbuckbunny.mp4").resolve()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copied = root / "copied.mp4"
            unrelated = root / "unrelated.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(reference), "-an", "-c:v", "libx264", "-crf", "28", str(copied)], check=True, capture_output=True, timeout=90)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(unrelated)], check=True, capture_output=True, timeout=90)
            self.assertEqual(match_claimed_content(copied, reference)["status"], "MATCH")
            self.assertEqual(match_claimed_content(unrelated, reference)["status"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
