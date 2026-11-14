import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.video_watermark import temporal_sample_indices
from watermark.content_match import match_claimed_content


class ContentMatchTests(unittest.TestCase):
    def test_temporal_plan_samples_every_two_seconds_and_keeps_the_final_frame(self):
        # 10 s at 30 fps: 0, 2, 4, 6 and 8 s plus the final frame. The
        # end-of-clip sample preserves coverage without returning to 1 fps.
        indices = temporal_sample_indices(300, 30)
        self.assertEqual(indices[:5], [0, 60, 120, 180, 240])
        self.assertEqual(indices[-1], 299)
        self.assertEqual(len(indices), 6)

    def test_reencoded_reference_matches_and_unrelated_video_does_not(self):
        reference = Path("data/media/bigbuckbunny.mp4").resolve()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copied = root / "copied.mp4"
            unrelated = root / "unrelated.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(reference), "-an", "-c:v", "libx264", "-crf", "28", str(copied)], check=True, capture_output=True, timeout=90)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(unrelated)], check=True, capture_output=True, timeout=90)
            matched = match_claimed_content(copied, reference)
            self.assertEqual(matched["status"], "MATCH")
            self.assertEqual(matched["sample_interval_seconds"], 2.0)
            self.assertIn("2s", matched["method"])
            self.assertEqual(match_claimed_content(unrelated, reference)["status"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
