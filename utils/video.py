from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Tuple

from services.content_provider import DatasetContentProvider, default_content_id
from utils.video_watermark import embed_video


MEDIA_ROOT = Path(__file__).resolve().parents[1] / "data" / "media"
GENERATED_ROOT = MEDIA_ROOT / "generated"
VISUAL_WATERMARK_VERSION = "independent-v7-keyed-spread-spectrum-48bit"
VIDEO_CATALOG = (
    ("bigbuckbunny", "Big Buck Bunny · clipe real", "bigbuckbunny.mp4"),
    ("cdn_sentinel_demo", "CDN-Sentinel demo · original", "cdn-sentinel-demo-original.mp4"),
    ("cdn_sentinel_demo_watermarked", "CDN-Sentinel demo · luminância watermark", "cdn-sentinel-demo-watermarked.mp4"),
    ("cdn_sentinel_demo_difference", "CDN-Sentinel demo · diferença amplificada", "cdn-sentinel-demo-difference.mp4"),
    ("bikes", "Bikes", "bikes.mp4"),
    ("carphone_pristine", "Carphone · original", "carphone_pristine.mp4"),
    ("carphone_distorted", "Carphone · variante", "carphone_distorted.mp4"),
)
_SAFE_GENERATED_ID = re.compile(r"^[a-f0-9]{16}$")


@lru_cache(maxsize=1)
def _dataset_root() -> Path:
    """Resolve the optional local scikit-video dataset directory."""
    from skvideo.datasets import bigbuckbunny

    return Path(bigbuckbunny()).parent


def list_video_examples() -> list[dict[str, str]]:
    """Return valid local MP4 examples, including downloaded dataset clips."""
    examples: list[dict[str, str]] = []
    for video_id, label, filename in VIDEO_CATALOG[:4]:
        path = MEDIA_ROOT / filename
        if path.is_file():
            examples.append(
                {
                    "video_id": video_id,
                    "label": label,
                    "filename": filename,
                    "content_type": "video/mp4",
                    "source": "Big Buck Bunny real · Blender Foundation / CC-BY-3.0"
                    if video_id == "bigbuckbunny"
                    else "versioned-local-demo",
                    "resolution": "1280x720" if video_id == "bigbuckbunny" else "320x180",
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
                for video_id, label, filename in VIDEO_CATALOG[4:]
                if (root / filename).is_file()
            )
    dataset_provider = DatasetContentProvider()
    for item in dataset_provider.list_catalog():
        relative_path = item.content_id.removeprefix("youtube_clipped_videos/")
        path = dataset_provider.root / relative_path
        content_type = item.content_type
        examples.append(
            {
                "video_id": item.content_id,
                "label": item.title,
                "filename": path.relative_to(dataset_provider.root).as_posix(),
                "content_type": content_type,
                "source": item.source,
                "resolution": "dataset",
                "size_bytes": str(path.stat().st_size),
            }
        )
    return examples


def choose_video_example(exclude_video_id: str | None = None) -> dict[str, str]:
    """Choose a deterministic local example, preferring the downloaded dataset."""
    examples = list_video_examples()
    if not examples:
        raise FileNotFoundError("nenhum vídeo MP4 local está disponível")
    dataset_examples = [
        item for item in examples if item["source"] == "kishan51/youtube_clipped_videos"
    ]
    if dataset_examples:
        candidates = [item for item in dataset_examples if item["video_id"] != exclude_video_id]
        if candidates:
            return candidates[0]
    preferred = next((item for item in examples if item["video_id"] == "bigbuckbunny"), None)
    if preferred and preferred["video_id"] != exclude_video_id:
        return preferred
    candidates = [item for item in examples if item["video_id"] != exclude_video_id] or examples
    return candidates[0]


def _generated_variant_path(generated_id: str, variant: str) -> Path:
    if not _SAFE_GENERATED_ID.fullmatch(generated_id):
        raise ValueError("identificador de variante gerada inválido")
    if variant not in {"watermarked", "difference"}:
        raise ValueError("variante gerada inválida")
    path = GENERATED_ROOT / f"{generated_id}-{variant}.mp4"
    if not path.is_file():
        raise FileNotFoundError(f"variante gerada não encontrada: {generated_id}/{variant}")
    if variant == "difference" and not _difference_is_valid(path):
        raise FileNotFoundError(f"variante de diferença inválida: {generated_id}; execute a demonstração novamente")
    return path


def get_video_asset(
    video_id: str | None = None,
    variant: str = "original",
    generated_id: str | None = None,
) -> tuple[Path, str]:
    """Resolve a named MP4 asset and MIME type without allowing path traversal."""
    video_id = video_id or default_content_id()
    if generated_id:
        return _generated_variant_path(generated_id, variant), "video/mp4"
    dataset_provider = DatasetContentProvider()
    if dataset_provider.supports(video_id):
        return dataset_provider.resolve_asset(video_id)
    aliases = {
        "original": default_content_id(),
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
    elif selected["source"] == "kishan51/youtube_clipped_videos":
        path, _ = dataset_provider.resolve_asset(selected_id)
    if not path.is_file():
        raise FileNotFoundError(f"vídeo não encontrado: {selected_id}")
    return path, selected["content_type"]


def _probe_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = result.stdout.strip().split("x", 1)
    return int(width), int(height)


def _difference_is_valid(path: Path) -> bool:
    """Reject stale/buggy cached difference videos that render as a white card."""
    try:
        frame = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    if not frame:
        return False
    average = sum(frame) / len(frame)
    return average < 128 and max(frame) - min(frame) >= 8


def generate_visual_variants(video_id: str, token: str, secret_key: str | None = None) -> str:
    """Create cached MP4 variants with the keyed visual marker embedded in frames."""
    source, _ = get_video_asset(video_id, "original")
    generated_id = hashlib.sha256(
        f"{VISUAL_WATERMARK_VERSION}:{source}:{source.stat().st_mtime_ns}:{token}".encode()
    ).hexdigest()[:16]
    watermarked = GENERATED_ROOT / f"{generated_id}-watermarked.mp4"
    difference = GENERATED_ROOT / f"{generated_id}-difference.mp4"
    if watermarked.is_file() and difference.is_file() and _difference_is_valid(difference):
        return generated_id

    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    partial_watermarked = watermarked.with_suffix(".part.mp4")
    partial_difference = difference.with_suffix(".part.mp4")
    try:
        embed_video(source, partial_watermarked, token, secret_key or os.getenv("CDN_SECRET_KEY", "local-development-secret"))
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-i", str(partial_watermarked),
                "-filter_complex", "[1:v][0:v]blend=all_mode=difference,eq=contrast=10:brightness=0.5",
                "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", str(partial_difference),
            ],
            check=True,
            capture_output=True,
        )
        if not _difference_is_valid(partial_difference):
            raise RuntimeError("a diferença visual gerada ficou saturada; variante descartada")
        partial_watermarked.replace(watermarked)
        partial_difference.replace(difference)
    finally:
        for partial in (partial_watermarked, partial_difference):
            if partial.exists():
                partial.unlink()
    return generated_id


def get_video_chunk(chunk_number: int = 0, video_id: str | None = None) -> Tuple[bytes, str]:
    """Return the deterministic local MP4 as a transport sample."""
    del chunk_number
    path, content_type = get_video_asset(video_id, "original")
    return path.read_bytes(), content_type


def encode_payload(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def extract_watermark_token(encoded_payload: str) -> str:
    """Extract the forensic prefix from a Base64 encoded leaked chunk."""
    raw = base64.b64decode(encoded_payload.encode("ascii"), validate=True)
    token = raw.split(b"\n", 1)[0].decode("utf-8")
    if not token.startswith(("CDNWM1.", "CDNWM2.", "CDNWM3.")):
        raise ValueError("chunk não contém prefixo de watermark")
    return token
