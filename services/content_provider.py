"""Content providers used by the CDN nodes and the Watermark Studio.

The local fallback keeps the demo runnable without downloading anything. When
the Hugging Face snapshot exists, :class:`HybridContentProvider` exposes its
video files through the same interface, so routing and watermarking do not
need to know where the content came from.
"""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


DATASET_REPO_ID = "kishan51/youtube_clipped_videos"
DATASET_CONTENT_ID = "youtube_clipped_videos"
DEFAULT_DATASET_ROOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "datasets"
    / "youtube_clipped_videos"
)
VIDEO_EXTENSIONS = frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"})


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


class DatasetContentProvider:
    """Read video assets from the downloaded Hugging Face dataset snapshot.

    The repository is intentionally treated as a directory of video assets,
    which works for the standard Hugging Face video-dataset layout (files at
    the root or below a ``videos/`` directory). A stable content id includes
    the relative path, avoiding collisions between clips with the same stem.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        configured_root = root or os.getenv("CDN_DATASET_ROOT") or DEFAULT_DATASET_ROOT
        self.root = Path(configured_root).expanduser().resolve()

    def _video_files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(
            (
                path
                for path in self.root.rglob("*")
                if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
            ),
            key=lambda path: path.relative_to(self.root).as_posix().lower(),
        )

    def _content_id(self, path: Path) -> str:
        relative_path = path.relative_to(self.root).as_posix()
        return f"{DATASET_CONTENT_ID}/{relative_path}"

    def supports(self, content_id: str) -> bool:
        """Return whether ``content_id`` belongs to this provider."""
        return content_id == DATASET_CONTENT_ID or content_id.startswith(
            f"{DATASET_CONTENT_ID}/"
        )

    def available(self) -> bool:
        return bool(self._video_files())

    def list_catalog(self) -> list[VideoCatalog]:
        catalog: list[VideoCatalog] = []
        for path in self._video_files():
            content_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
            catalog.append(
                VideoCatalog(
                    content_id=self._content_id(path),
                    title=f"YouTube clip · {path.stem}",
                    source=DATASET_REPO_ID,
                    content_type=content_type,
                )
            )
        return catalog

    def resolve_asset(self, content_id: str, chunk_number: int = 0) -> tuple[Path, str]:
        """Resolve a dataset id to a local video path.

        The dataset id selects a deterministic clip when ``content_id`` is the
        dataset selector itself. Individual catalog ids select an exact file;
        arbitrary filesystem paths are never accepted.
        """
        if not self.supports(content_id):
            raise KeyError(f"conteúdo não pertence ao dataset: {content_id}")
        files = self._video_files()
        if not files:
            raise FileNotFoundError(
                f"dataset {DATASET_REPO_ID} não encontrado em {self.root}; "
                "execute o downloader antes de selecioná-lo"
            )
        if content_id == DATASET_CONTENT_ID:
            path = files[chunk_number % len(files)]
        else:
            requested_relative = content_id.removeprefix(f"{DATASET_CONTENT_ID}/")
            path = next(
                (
                    candidate
                    for candidate in files
                    if candidate.relative_to(self.root).as_posix() == requested_relative
                ),
                None,
            )
            if path is None:
                raise FileNotFoundError(f"vídeo do dataset não encontrado: {content_id}")
        return path, mimetypes.guess_type(path.name)[0] or "video/mp4"

    def get_chunk(self, content_id: str, chunk_number: int) -> tuple[bytes, str]:
        path, content_type = self.resolve_asset(content_id, chunk_number)
        return path.read_bytes(), content_type


def default_content_id() -> str:
    """Use the downloaded dataset whenever it is available locally."""
    return DATASET_CONTENT_ID if DatasetContentProvider().available() else "bigbuckbunny"


class HybridContentProvider:
    """Prefer downloaded dataset content and retain the local demo fallback."""

    def __init__(
        self,
        dataset_provider: DatasetContentProvider | None = None,
        fallback_provider: ContentProvider | None = None,
    ) -> None:
        self.dataset_provider = dataset_provider or DatasetContentProvider()
        self.fallback_provider = fallback_provider or FallbackContentProvider()

    def get_chunk(self, content_id: str, chunk_number: int) -> tuple[bytes, str]:
        if self.dataset_provider.supports(content_id):
            return self.dataset_provider.get_chunk(content_id, chunk_number)
        return self.fallback_provider.get_chunk(content_id, chunk_number)

