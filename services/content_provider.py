"""Small content abstraction used by the prototype.

The default provider is deterministic in-memory bytes, so the demo does not
need a database, cloud bucket or external dataset. A future provider can
implement the same interface without changing routing or watermark services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ContentProvider(Protocol):
    def get_chunk(self, content_id: str, chunk_number: int) -> tuple[bytes, str]: ...


@dataclass(frozen=True)
class VideoCatalog:
    content_id: str
    title: str
    source: str = "local-fallback"
    content_type: str = "video/mp4"


class FallbackContentProvider:
    def get_chunk(self, content_id: str, chunk_number: int) -> tuple[bytes, str]:
        from utils.video import get_video_chunk

        return get_video_chunk(chunk_number, content_id)

