from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path
from typing import Tuple


MEDIA_ROOT = Path(__file__).resolve().parents[1] / "data" / "media"
VIDEO_CATALOG = (
    ("cdn_sentinel_demo", "CDN-Sentinel demo · original", "cdn-sentinel-demo-original.mp4"),
    ("cdn_sentinel_demo_watermarked", "CDN-Sentinel demo · luminância watermark", "cdn-sentinel-demo-watermarked.mp4"),
    ("cdn_sentinel_demo_difference", "CDN-Sentinel demo · diferença amplificada", "cdn-sentinel-demo-difference.mp4"),
    ("bigbuckbunny", "Big Buck Bunny", "bigbuckbunny.mp4"),
    ("bikes", "Bikes", "bikes.mp4"),
    ("carphone_pristine", "Carphone · original", "carphone_pristine.mp4"),
    ("carphone_distorted", "Carphone · variante", "carphone_distorted.mp4"),
)


@lru_cache(maxsize=1)
def _dataset_root() -> Path:
    """Resolve the local scikit-video dataset directory."""
    from skvideo.datasets import bigbuckbunny

    return Path(bigbuckbunny()).parent


def list_video_examples() -> list[dict[str, str]]:
    """Return valid local MP4 examples; external dataset entries are opt-in."""
    examples: list[dict[str, str]] = []
    for video_id, label, filename in VIDEO_CATALOG[:3]:
        path = MEDIA_ROOT / filename
        if path.is_file():
            examples.append(
                {
                    "video_id": video_id,
                    "label": label,
                    "filename": filename,
                    "content_type": "video/mp4",
                    "source": "versioned-local-demo",
                    "resolution": "320x180",
                    "size_bytes": str(path.stat().st_size),
                }
            )
    if os.getenv("USE_BIGBUCKBUNNY_DATASET", "0") == "1":
        try:
            root = _dataset_root()
        except (ImportError, OSError, TypeError):
            root = None
        if root:
            examples.extend(
                {
                    "video_id": video_id,
                    "label": label,
                    "filename": filename,
                    "content_type": "video/mp4",
                    "source": "scikit-video-local",
                }
                for video_id, label, filename in VIDEO_CATALOG[3:]
                if (root / filename).is_file()
            )
    return examples


def choose_video_example(exclude_video_id: str | None = None) -> dict[str, str]:
    """Choose a deterministic local example without network or random state."""
    examples = list_video_examples()
    if not examples:
        raise FileNotFoundError("nenhum vídeo MP4 local está disponível")
    candidates = [item for item in examples if item["video_id"] != exclude_video_id] or examples
    return candidates[0]


def get_video_asset(video_id: str = "cdn_sentinel_demo", variant: str = "original") -> tuple[Path, str]:
    """Resolve a named valid MP4 asset and MIME type."""
    aliases = {
        "bigbuckbunny": "cdn_sentinel_demo",
        "original": "cdn_sentinel_demo",
        "watermarked": "cdn_sentinel_demo_watermarked",
        "difference": "cdn_sentinel_demo_difference",
    }
    selected_id = aliases.get(video_id, video_id)
    if video_id == "cdn_sentinel_demo" and variant in {"watermarked", "difference"}:
        selected_id = f"cdn_sentinel_demo_{variant}"
    examples = {item["video_id"]: item for item in list_video_examples()}
    selected = examples.get(selected_id)
    if selected is None:
        raise ValueError(f"exemplo de vídeo inválido: {selected_id}")
    path = MEDIA_ROOT / selected["filename"]
    if selected["source"] == "scikit-video-local":
        path = _dataset_root() / selected["filename"]
    if not path.is_file():
        raise FileNotFoundError(f"vídeo não encontrado: {selected_id}")
    return path, selected["content_type"]


def get_video_chunk(chunk_number: int = 0, video_id: str = "cdn_sentinel_demo") -> Tuple[bytes, str]:
    """Return the deterministic local MP4 as a transport sample.

    The stream API prefixes a forensic claim for transport, so that response is
    not itself advertised as a directly playable MP4. The Watermark Studio
    uses :func:`get_video_asset` for HTML5 playback.
    """
    del chunk_number
    path, content_type = get_video_asset(video_id)
    return path.read_bytes(), content_type


def encode_payload(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def extract_watermark_token(encoded_payload: str) -> str:
    """Extract the forensic prefix from a Base64 encoded leaked chunk."""
    raw = base64.b64decode(encoded_payload.encode("ascii"), validate=True)
    token = raw.split(b"\n", 1)[0].decode("utf-8")
    if not token.startswith("CDNWM1."):
        raise ValueError("chunk não contém prefixo de watermark")
    return token
