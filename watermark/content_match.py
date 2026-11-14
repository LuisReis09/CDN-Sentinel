"""Conservative local content check for a claimed video.

The visual identifier alone can be transplanted onto unrelated media.  This
matcher checks ordered frame fingerprints against the claimed catalog asset.
It is a screening gate, not a calibrated copyright identifier.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np

from utils.video_watermark import FORENSIC_SAMPLE_INTERVAL_SECONDS, probe_video_limits, temporal_sample_indices


def frame_hashes(
    path: Path,
    *,
    max_seconds: int = 30,
    sample_interval_seconds: float = FORENSIC_SAMPLE_INTERVAL_SECONDS,
) -> list[tuple[int, float, float]]:
    """Hash the bounded delivery window used by the CDN leak detector.

    A leaked delivery is a short segment, not an entire catalog movie. The
    previous 180-second upper bound made every authenticated investigation
    decode far beyond the received chunk and serialized blacklist progress.
    The content gate also samples independent frames every two seconds instead
    of every second.  The terminal frame is included to retain three
    observations for a four-second forensic-studio clip.
    """
    if max_seconds <= 0:
        raise ValueError("max_seconds deve ser positivo")
    metadata = probe_video_limits(path)
    fps = float(metadata["fps"])
    duration = float(metadata["duration_seconds"])
    if duration <= 0:
        raise ValueError("duração de vídeo inválida")
    # ``duration * fps`` can be fractionally above the stream's real frame
    # count (for example 4.004 s at 29.97003 fps is exactly 120 frames).
    # Round rather than ceil so the terminal index remains decodable.
    window_frames = max(1, round(min(duration, max_seconds) * fps))
    max_samples = max(1, math.ceil(max_seconds / sample_interval_seconds) + 1)
    indices = temporal_sample_indices(
        window_frames,
        fps,
        interval_seconds=sample_interval_seconds,
        max_frames=max_samples,
    )
    select_expression = "+".join(f"eq(n,{index})" for index in indices) or "eq(n,0)"
    command = [
        "ffmpeg", "-v", "error", "-t", str(max_seconds), "-i", str(path), "-an",
        "-vf", f"select='{select_expression}',scale=16:16:flags=area,format=gray",
        "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, check=True, timeout=90)
    hashes: list[tuple[int, float, float]] = []
    raw = result.stdout
    for offset in range(0, len(raw) - 255, 256):
        pixels = np.frombuffer(raw[offset:offset + 256], dtype=np.uint8).reshape(16, 16)
        # Four-pixel regional means resist modest codec/resize changes.
        cells = pixels.reshape(8, 2, 8, 2).mean(axis=(1, 3))
        threshold = float(np.median(cells))
        value = 0
        for bit in (cells > threshold).flat:
            value = (value << 1) | int(bit)
        hashes.append((value, float(pixels.mean()), float(pixels.std())))
    return hashes


def match_claimed_content(suspect: Path, reference: Path) -> dict:
    received = frame_hashes(suspect)
    original = frame_hashes(reference)
    if len(received) < 3 or len(original) < 3:
        return {
            "status": "INCONCLUSIVE",
            "reason": "menos de três amostras temporais disponíveis",
            "matched_frames": 0,
            "sample_interval_seconds": FORENSIC_SAMPLE_INTERVAL_SECONDS,
        }
    best = {"matched_frames": 0, "median_hamming": 64.0, "offset_samples": 0, "offset_seconds": 0.0, "fraction": 0.0}
    # Integer offsets support a partial clip and dropped edges.  A frame
    # must meet an absolute distance threshold; sequence order must agree.
    for offset in range(-len(received) + 1, len(original)):
        comparisons = [
            (received[index], original[index + offset])
            for index in range(len(received)) if 0 <= index + offset < len(original)
        ]
        if len(comparisons) < 3:
            continue
        distances = [(left[0] ^ right[0]).bit_count() for left, right in comparisons]
        matched = sum(
            distance <= 10 and abs(left[1] - right[1]) <= 14 and abs(left[2] - right[2]) <= 10
            and min(left[2], right[2]) >= 12
            for (left, right), distance in zip(comparisons, distances)
        )
        fraction = matched / len(comparisons)
        if (matched, fraction, -float(np.median(distances))) > (
            best["matched_frames"], best["fraction"], -best["median_hamming"]
        ):
            best = {
                "matched_frames": matched,
                "median_hamming": float(np.median(distances)),
                "offset_samples": offset,
                "offset_seconds": round(offset * FORENSIC_SAMPLE_INTERVAL_SECONDS, 3),
                "fraction": round(fraction, 4),
            }
    status = "MATCH" if best["matched_frames"] >= 3 and best["fraction"] >= 0.6 else "INCONCLUSIVE"
    return {
        "status": status,
        **best,
        "method": "ordered-2s-64bit-regional-hash-plus-luma-statistics",
        "sample_interval_seconds": FORENSIC_SAMPLE_INTERVAL_SECONDS,
        "threshold_hamming": 10,
    }
