from __future__ import annotations

import hashlib
from typing import Callable


GRID = 64
BLOCK = 8
BITS = (GRID // BLOCK) ** 2


def _seed_samples(content: bytes) -> list[int]:
    digest = hashlib.sha256(content).digest() or b"cdn"
    return [((content[index % len(content)] if content else 127) + digest[index % len(digest)] + index * 17) % 256 for index in range(GRID * GRID)]


def _bits(marker: str) -> list[int]:
    raw = bytes.fromhex(marker[:16].ljust(16, "0"))
    return [(byte >> bit) & 1 for byte in raw for bit in range(8)]


def embed_spread_spectrum(content: bytes, marker: str) -> tuple[list[int], list[int]]:
    """Embed a low-frequency signed marker into a synthetic luminance frame.

    This is intentionally a small, dependency-free prototype for the studio. A
    production implementation would run the same concept over decoded Y planes
    and needs a blind detector plus codec-specific calibration.
    """
    baseline = _seed_samples(content)
    watermarked = baseline.copy()
    for bit_index, bit in enumerate(_bits(marker)):
        row = (bit_index // (GRID // BLOCK)) * BLOCK
        col = (bit_index % (GRID // BLOCK)) * BLOCK
        delta = 7 if bit else -7
        for y in range(row, row + BLOCK):
            for x in range(col, col + BLOCK):
                position = y * GRID + x
                watermarked[position] = max(0, min(255, watermarked[position] + delta))
    return baseline, watermarked


def _blur(samples: list[int]) -> list[int]:
    output = samples.copy()
    for y in range(GRID):
        for x in range(GRID):
            values = [samples[yy * GRID + xx] for yy in range(max(0, y - 1), min(GRID, y + 2)) for xx in range(max(0, x - 1), min(GRID, x + 2))]
            output[y * GRID + x] = round(sum(values) / len(values))
    return output


def _noise(samples: list[int]) -> list[int]:
    return [max(0, min(255, value + (((index * 37) % 5) - 2))) for index, value in enumerate(samples)]


def _reencode(samples: list[int]) -> list[int]:
    return [round(value / 4) * 4 for value in samples]


def _extract(samples: list[int], baseline: list[int], marker: str) -> tuple[str, float, int, int]:
    recovered: list[int] = []
    correct = 0
    expected = _bits(marker)
    for bit_index, expected_bit in enumerate(expected):
        row = (bit_index // (GRID // BLOCK)) * BLOCK
        col = (bit_index % (GRID // BLOCK)) * BLOCK
        values = [samples[y * GRID + x] - baseline[y * GRID + x] for y in range(row, row + BLOCK) for x in range(col, col + BLOCK)]
        bit = 1 if sum(values) >= 0 else 0
        recovered.append(bit)
        correct += int(bit == expected_bit)
    output = bytearray()
    for start in range(0, len(recovered), 8):
        output.append(sum(recovered[start + bit] << bit for bit in range(8)))
    total = len(expected)
    return output.hex(), correct / total if total else 0, correct, total


def assess_robustness(content: bytes, token: str) -> list[dict]:
    marker = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    baseline, embedded = embed_spread_spectrum(content, marker)
    transforms: list[tuple[str, str, Callable[[list[int]], list[int]]]] = [
        ("sem filtro", "controle", lambda values: values),
        ("borramento leve", "blur", _blur),
        ("ruído de transmissão", "noise", _noise),
        ("re-encode/quantização", "reencode", _reencode),
    ]
    checks = []
    for label, filter_id, transform in transforms:
        recovered, confidence, bits_correct, bits_total = _extract(transform(embedded), baseline, marker)
        checks.append({
            "filter": label,
            "filter_id": filter_id,
            "marker": marker,
            "recovered_marker": recovered,
            "confidence": round(confidence, 3),
            "bits_correct": bits_correct,
            "bits_total": bits_total,
            "confidence_method": "bits corretamente recuperados / bits do marcador",
            "survives": confidence >= 0.9,
        })
    return checks
