import unittest

from utils.video import get_video_chunk


class VideoContractTests(unittest.TestCase):
    def test_legacy_helper_does_not_return_whole_asset_for_another_chunk(self):
        with self.assertRaisesRegex(ValueError, "no temporal chunks"):
            get_video_chunk(1, "cdn_sentinel_demo")


if __name__ == "__main__":
    unittest.main()
