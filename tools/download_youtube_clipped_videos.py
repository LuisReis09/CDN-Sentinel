#!/usr/bin/env python3
"""Download the YouTube clips used by CDN-Sentinel.

The snapshot is kept outside Git and can be resumed safely by running this
command again. The backend discovers video files below the destination
directory automatically.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


REPOSITORY_ID = "kishan51/youtube_clipped_videos"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = PROJECT_ROOT / "data" / "datasets" / "youtube_clipped_videos"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Baixa o dataset de clipes do YouTube para o CDN-Sentinel."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
        help=f"diretório local de destino (padrão: {DEFAULT_DESTINATION})",
    )
    parser.add_argument(
        "--revision",
        help="branch, tag ou commit do dataset; por padrão usa a revisão principal",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("HF_TOKEN"),
        help="token opcional do Hugging Face; por padrão usa HF_TOKEN",
    )
    return parser.parse_args()


def download_dataset(
    destination: Path = DEFAULT_DESTINATION,
    revision: str | None = None,
    token: str | None = None,
) -> Path:
    """Download or resume the dataset snapshot and return its local path."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "Dependência ausente: instale as dependências com "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "repo_id": REPOSITORY_ID,
        "repo_type": "dataset",
        "local_dir": str(destination),
    }
    if revision:
        kwargs["revision"] = revision
    if token:
        kwargs["token"] = token
    snapshot_download(**kwargs)
    return destination


def main() -> int:
    args = parse_args()
    try:
        destination = download_dataset(args.destination, args.revision, args.token)
    except Exception as exc:
        print(f"Erro ao baixar {REPOSITORY_ID}: {exc}")
        return 1

    video_count = sum(
        1
        for path in destination.rglob("*")
        if path.is_file() and path.suffix.lower() in {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
    )
    print(f"Dataset disponível em: {destination}")
    print(f"Arquivos de vídeo encontrados: {video_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
