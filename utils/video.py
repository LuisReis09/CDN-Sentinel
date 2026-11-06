from __future__ import annotations

import base64
import hashlib
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Tuple


VIDEO_CATALOG = (
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
    """Return real video examples available in the backend dataset."""
    try:
        root = _dataset_root()
    except (ImportError, OSError, TypeError):
        return []
    return [
        {"video_id": video_id, "label": label, "filename": filename, "content_type": "video/mp4", "source": "scikit-video-local"}
        for video_id, label, filename in VIDEO_CATALOG
        if (root / filename).is_file()
    ]


def choose_video_example(exclude_video_id: str | None = None) -> dict[str, str]:
    """Choose another real example when possible, otherwise use Big Buck Bunny."""
    examples = list_video_examples()
    if not examples:
        return {"video_id": "bigbuckbunny", "label": "Fallback determinístico", "filename": "", "content_type": "application/octet-stream", "source": "deterministic-local-fallback"}
    candidates = [item for item in examples if item["video_id"] != exclude_video_id] or examples
    return secrets.choice(candidates)


def get_video_asset(video_id: str = "bigbuckbunny") -> tuple[Path, str]:
    """Resolve a named real video asset from the backend environment."""
    examples = {item["video_id"]: item for item in list_video_examples()}
    if not examples:
        raise FileNotFoundError("dataset de vídeos não está disponível no backend")
    selected = examples.get(video_id)
    if selected is None:
        raise ValueError(f"exemplo de vídeo inválido: {video_id}")
    path = _dataset_root() / selected["filename"]
    if not path.is_file():
        raise FileNotFoundError(f"dataset não contém o vídeo {video_id}")
    return path, selected["content_type"]


def get_video_chunk(chunk_number: int = 0, video_id: str = "bigbuckbunny") -> Tuple[bytes, str]:
    """Return a lightweight chunk from a real dataset video."""
    # Offline deterministic fallback is the default for Entrega 2. An
    # operator may opt into locally installed scikit-video assets explicitly.
    if os.getenv("USE_BIGBUCKBUNNY_DATASET", "0") == "1":
        try:
            path, content_type = get_video_asset(video_id)
            with path.open("rb") as video_file:
                video_file.seek((chunk_number * 4096) % 65536)
                payload = video_file.read(1024)
            if payload:
                return payload, content_type
        except (ImportError, OSError, TypeError):
            if video_id != "bigbuckbunny":
                raise
    seed = hashlib.sha256(f"bigbuckbunny-simulated-{chunk_number}".encode()).digest()
    return (seed * 64)[:1024], "application/octet-stream"


def encode_payload(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def extract_watermark_token(encoded_payload: str) -> str:
    """Extract the forensic prefix from a Base64 encoded leaked chunk."""
    raw = base64.b64decode(encoded_payload.encode("ascii"), validate=True)
    token = raw.split(b"\n", 1)[0].decode("utf-8")
    if not token.startswith("CDNWM1."):
        raise ValueError("chunk não contém prefixo de watermark")
    return token
