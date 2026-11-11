import tempfile
import unittest
from pathlib import Path

from services.content_provider import DATASET_CONTENT_ID, DatasetContentProvider, HybridContentProvider, default_content_id


class ContentProviderTests(unittest.TestCase):
    def test_default_content_prefers_downloaded_dataset_and_falls_back_to_bbb(self):
        provider = DatasetContentProvider()
        expected = DATASET_CONTENT_ID if provider.available() else "bigbuckbunny"
        self.assertEqual(default_content_id(), expected)

    def test_dataset_provider_discovers_video_files_and_reads_selector(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "videos").mkdir()
            first = root / "videos" / "clip-a.mp4"
            second = root / "videos" / "clip-b.webm"
            first.write_bytes(b"clip-a")
            second.write_bytes(b"clip-b")

            provider = DatasetContentProvider(root)
            catalog = provider.list_catalog()

            self.assertEqual(len(catalog), 2)
            self.assertEqual(catalog[0].content_id, "youtube_clipped_videos/videos/clip-a.mp4")
            payload, content_type = provider.get_chunk("youtube_clipped_videos", 1)
            self.assertEqual(payload, b"clip-b")
            self.assertEqual(content_type, "video/webm")

    def test_hybrid_provider_keeps_fallback_for_non_dataset_content(self):
        class StubFallback:
            def get_chunk(self, content_id: str, chunk_number: int) -> tuple[bytes, str]:
                return f"{content_id}:{chunk_number}".encode(), "video/test"

        provider = HybridContentProvider(
            dataset_provider=DatasetContentProvider(tempfile.mkdtemp()),
            fallback_provider=StubFallback(),
        )
        payload, content_type = provider.get_chunk("bigbuckbunny", 3)
        self.assertEqual(payload, b"bigbuckbunny:3")
        self.assertEqual(content_type, "video/test")


if __name__ == "__main__":
    unittest.main()
