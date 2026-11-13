"""Reproducible image-watermark benchmark.

The benchmark intentionally uses deterministic synthetic RGB images so it can
run in CI without downloading media. It measures perceptual distortion,
independent detection, negative controls, and operation latency.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.watermark_service import WatermarkService
from utils.image_watermark import detect_image, embed_image, visual_marker


def _fixture(size: int = 256, seed: int = 2026) -> Image.Image:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size]
    base = np.stack(
        [
            65 + 100 * x / max(1, size - 1),
            55 + 90 * y / max(1, size - 1),
            80 + 60 * ((x + y) % max(1, size)) / max(1, size - 1),
        ],
        axis=2,
    )
    noise = rng.normal(0, 5, size=(size, size, 1))
    return Image.fromarray(np.uint8(np.clip(base + noise, 0, 255)), "RGB")


def _psnr(original: Image.Image, candidate: Image.Image) -> float:
    left = np.asarray(original.convert("RGB"), dtype=np.float64)
    right = np.asarray(candidate.convert("RGB"), dtype=np.float64)
    mse = float(np.mean((left - right) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10((255.0**2) / mse)


def _ssim_global(original: Image.Image, candidate: Image.Image) -> float:
    left = np.asarray(original.convert("L"), dtype=np.float64)
    right = np.asarray(candidate.convert("L"), dtype=np.float64)
    c1, c2 = 6.5025, 58.5225
    mean_left, mean_right = left.mean(), right.mean()
    variance_left, variance_right = left.var(), right.var()
    covariance = float(np.mean((left - mean_left) * (right - mean_right)))
    return float(((2 * mean_left * mean_right + c1) * (2 * covariance + c2)) / ((mean_left**2 + mean_right**2 + c1) * (variance_left + variance_right + c2)))


def _jpeg(image: Image.Image, quality: int = 80) -> Image.Image:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def run(size: int = 256, negatives: int = 32) -> dict:
    service = WatermarkService("benchmark-secret")
    token, _claim = service.issue("benchmark-client", "benchmark-server", 0, "benchmark-video")
    original = _fixture(size)
    started = time.perf_counter()
    marked, metadata = embed_image(original, token, service.secret_key)
    embed_ms = (time.perf_counter() - started) * 1000

    transformations = {
        "marked": marked,
        "jpeg_q80": _jpeg(marked, 80),
        "blur_radius_1": marked.filter(ImageFilter.GaussianBlur(1)),
        "resize_half_then_restore": marked.resize((size // 2, size // 2), Image.Resampling.LANCZOS).resize((size, size), Image.Resampling.LANCZOS),
        "plain": original,
    }
    detections: dict[str, dict] = {}
    for name, image in transformations.items():
        started = time.perf_counter()
        evidence = service.detect_image(image)
        detections[name] = {
            "status": evidence["status"],
            "marker_match": evidence.get("marker") == visual_marker(token),
            "confidence": evidence.get("confidence", 0.0),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    false_positive_candidates = 0
    false_positive_valid = 0
    false_positive_statuses: dict[str, int] = {}
    for seed in range(negatives):
        image = Image.fromarray(np.random.default_rng(seed).integers(0, 256, size=(size, size, 3), dtype=np.uint8), "RGB")
        raw_status = detect_image(image, service.secret_key)["status"]
        status = service.detect_image(image)["status"]
        false_positive_statuses[status] = false_positive_statuses.get(status, 0) + 1
        false_positive_candidates += int(raw_status == "CANDIDATE")
        false_positive_valid += int(status == "VALID")

    algorithm = dict(metadata)
    algorithm["layout"] = asdict(metadata["layout"])
    return {
        "fixture": {"kind": "deterministic-gradient-plus-noise", "size": [size, size], "seed": 2026},
        "algorithm": algorithm,
        "expected_marker": visual_marker(token),
        "perceptual": {
            "psnr_db": round(_psnr(original, marked), 4),
            "ssim_global": round(_ssim_global(original, marked), 6),
        },
        "detections": detections,
        "negative_control": {
            "samples": negatives,
            "raw_candidate_false_positives": false_positive_candidates,
            "raw_candidate_false_positive_rate": round(false_positive_candidates / max(1, negatives), 6),
            "verified_valid_false_positives": false_positive_valid,
            "statuses": false_positive_statuses,
        },
        "embed_elapsed_ms": round(embed_ms, 3),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--negatives", type=int, default=32)
    args = parser.parse_args()
    print(json.dumps(run(args.size, args.negatives), ensure_ascii=False, indent=2))
