"""Conservative local content check for a claimed video.

The visual identifier alone can be transplanted onto unrelated media.  This
matcher checks ordered frame fingerprints against the claimed catalog asset.
It is a screening gate, not a calibrated copyright identifier.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np


def frame_hashes(path: Path, *, max_seconds: int = 180) -> list[tuple[int, float, float]]:
    command = [
        "ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", "fps=1,scale=16:16:flags=area,format=gray",
        "-frames:v", str(max_seconds), "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
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
        return {"status": "INCONCLUSIVE", "reason": "menos de três frames de 1 s disponíveis", "matched_frames": 0}
    best = {"matched_frames": 0, "median_hamming": 64.0, "offset_seconds": 0, "fraction": 0.0}
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
            best = {"matched_frames": matched, "median_hamming": float(np.median(distances)), "offset_seconds": offset, "fraction": round(fraction, 4)}
    status = "MATCH" if best["matched_frames"] >= 3 and best["fraction"] >= 0.6 else "INCONCLUSIVE"
    return {"status": status, **best, "method": "ordered-1fps-64bit-regional-hash-plus-luma-statistics", "threshold_hamming": 10}
