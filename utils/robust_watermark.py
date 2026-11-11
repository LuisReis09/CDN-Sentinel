"""Legacy byte-level watermark test helper.

The live image/video path uses ``utils.image_watermark`` and
``utils.video_watermark``. This module remains for compatibility with the
original byte-transform unit tests and is not used by Watermark Studio.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path


GRID = 64
BLOCK = 8
BITS = (GRID // BLOCK) ** 2


def marker_bits(marker: str) -> list[int]:
    raw = bytes.fromhex(marker[:16].ljust(16, "0"))
    return [(byte >> bit) & 1 for byte in raw for bit in range(8)]


def signal_rects(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Return the 8x8 regions used by the legacy byte-transform signal."""
    margin_x = max(4, int(width * 0.04))
    margin_y = max(4, int(height * 0.04))
    step_x = (width - 2 * margin_x) / 8
    step_y = (height - 2 * margin_y) / 8
    return [
        (
            int(margin_x + col * step_x + step_x * 0.18),
            int(margin_y + row * step_y + step_y * 0.18),
            max(2, int(step_x * 0.64)),
            max(2, int(step_y * 0.64)),
        )
        for row in range(8)
        for col in range(8)
    ]


def _seed_samples(content: bytes) -> list[int]:
    digest = hashlib.sha256(content).digest() or b"cdn"
    return [
        ((content[index % len(content)] if content else 127) + digest[index % len(digest)] + index * 17) % 256
        for index in range(GRID * GRID)
    ]


def _bits(marker: str) -> list[int]:
    return marker_bits(marker)


def embed_spread_spectrum(content: bytes, marker: str) -> tuple[list[int], list[int]]:
    """Compatibility prototype retained for unit tests and offline explanations."""
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
            values = [
                samples[yy * GRID + xx]
                for yy in range(max(0, y - 1), min(GRID, y + 2))
                for xx in range(max(0, x - 1), min(GRID, x + 2))
            ]
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
        values = [
            samples[y * GRID + x] - baseline[y * GRID + x]
            for y in range(row, row + BLOCK)
            for x in range(col, col + BLOCK)
        ]
        bit = 1 if sum(values) >= 0 else 0
        recovered.append(bit)
        correct += int(bit == expected_bit)
    output = bytearray()
    for start in range(0, len(recovered), 8):
        output.append(sum(recovered[start + bit] << bit for bit in range(8)))
    total = len(expected)
    return output.hex(), correct / total if total else 0, correct, total


def assess_robustness(content: bytes, token: str) -> list[dict]:
    """Compatibility assessment for the dependency-free prototype."""
    marker = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    baseline, embedded = embed_spread_spectrum(content, marker)
    transforms = [
        ("sem filtro", "controle", lambda values: values),
        ("borramento leve", "blur", _blur),
        ("ruído de transmissão", "noise", _noise),
        ("re-encode/quantização", "reencode", _reencode),
    ]
    checks = []
    for label, filter_id, transform in transforms:
        recovered, confidence, bits_correct, bits_total = _extract(transform(embedded), transform(baseline), marker)
        checks.append(
            {
                "filter": label,
                "filter_id": filter_id,
                "marker": marker,
                "recovered_marker": recovered,
                "confidence": round(confidence, 3),
                "bits_correct": bits_correct,
                "bits_total": bits_total,
                "confidence_method": "bits corretamente recuperados / bits do marcador",
                "survives": confidence >= 0.9,
            }
        )
    return checks


def assess_video_robustness(original_path: Path, watermarked_path: Path, token: str) -> list[dict]:
    """Generate real transformed samples and measure the monitor's recovery."""

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(original_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = (int(value) for value in probe.stdout.strip().split("x", 1))
    marker = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    transforms = [
        ("sem filtro", "controle", "controle", None, 18),
        ("borramento leve", "blur-light", "intensidade 1", "boxblur=1:1", 24),
        ("borramento forte", "blur-heavy", "intensidade 4", "boxblur=4:2", 24),
        ("ruído de transmissão leve", "noise-light", "4/255", "noise=alls=4:allf=u:all_seed=1234", 24),
        ("ruído de transmissão forte", "noise-heavy", "18/255", "noise=alls=18:allf=u:all_seed=1234", 24),
        ("re-encode qualidade alta", "reencode-high", "CRF 23", None, 23),
        ("re-encode qualidade baixa", "reencode-low", "CRF 38", None, 38),
        ("escala + re-encode", "resize-reencode", "50% → 100% / CRF 34", "scale=iw/2:ih/2,scale=iw*2:ih*2", 34),
    ]
    checks: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="cdn-sentinel-robustness-") as temp_dir:
        temp_root = Path(temp_dir)
        for label, filter_id, intensity, filter_expression, crf in transforms:
            sample_generated = filter_id != "controle"
            if sample_generated:
                original_sample = temp_root / f"{filter_id}-original.mp4"
                watermarked_sample = temp_root / f"{filter_id}-watermarked.mp4"
                _render_transform_sample(original_path, original_sample, filter_expression, crf)
                _render_transform_sample(watermarked_path, watermarked_sample, filter_expression, crf)
                baseline = _decode_first_frame(original_sample)
                embedded = _decode_first_frame(watermarked_sample)
            else:
                baseline = _decode_first_frame(original_path)
                embedded = _decode_first_frame(watermarked_path)
            recovered, confidence, bits_correct, bits_total = _extract_video_marker(baseline, embedded, width, height, marker)
            checks.append(
                {
                    "filter": label,
                    "filter_id": filter_id,
                    "intensity": intensity,
                    "marker": marker,
                    "recovered_marker": recovered,
                    "confidence": round(confidence, 3),
                    "bits_correct": bits_correct,
                    "bits_total": bits_total,
                    "sample_generated": sample_generated,
                    "sample_method": "amostra MP4 H.264 real de 1s, mesma transformação aplicada ao original e ao watermark",
                    "confidence_method": "bits corretamente recuperados / 64 bits do sinal HMAC após decodificação do primeiro frame da amostra",
                    "survives": confidence >= 0.9,
                }
            )
    return checks


def _decode_first_frame(path: Path, filter_expression: str | None = None) -> bytes:
    command = ["ffmpeg", "-v", "error", "-i", str(path)]
    if filter_expression:
        command.extend(["-vf", filter_expression])
    command.extend(["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"])
    return subprocess.run(command, check=True, capture_output=True).stdout


def _render_transform_sample(input_path: Path, output_path: Path, filter_expression: str | None, crf: int) -> None:
    """Create a short, real H.264 sample before the monitor measures it."""

    command = ["ffmpeg", "-y", "-v", "error", "-i", str(input_path), "-t", "1"]
    if filter_expression:
        command.extend(["-vf", filter_expression])
    command.extend([
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        str(output_path),
    ])
    subprocess.run(command, check=True, capture_output=True)


def _quantize(frame: bytes) -> bytes:
    return bytes((value // 4) * 4 for value in frame)


def _extract_video_marker(
    baseline: bytes,
    embedded: bytes,
    width: int,
    height: int,
    marker: str,
) -> tuple[str, float, int, int]:
    expected = marker_bits(marker)
    recovered: list[int] = []
    correct = 0
    rects = signal_rects(width, height)
    for expected_bit, (x, y, block_width, block_height) in zip(expected, rects):
        delta = 0
        for row in range(y, min(height, y + block_height)):
            start = row * width + x
            end = row * width + min(width, x + block_width)
            delta += sum(embedded[start:end]) - sum(baseline[start:end])
        bit = int(delta >= 0)
        recovered.append(bit)
        correct += int(bit == expected_bit)
    recovered_bytes = bytearray()
    for start in range(0, len(recovered), 8):
        recovered_bytes.append(sum(recovered[start + bit] << bit for bit in range(8)))
    total = len(expected)
    return recovered_bytes.hex(), correct / total if total else 0, correct, total


def assess_video_robustness_legacy(original_path: Path, watermarked_path: Path, token: str) -> list[dict]:
    """Measure recovery from the first real video frame after real transforms."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(original_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = (int(value) for value in probe.stdout.strip().split("x", 1))
    marker = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    transforms = [
        ("sem filtro", "controle", None, None),
        ("borramento leve", "blur", "boxblur=2:1", "boxblur=2:1"),
        ("ruído de transmissão", "noise", "noise=alls=4:allf=u", "noise=alls=4:allf=u"),
    ]
    checks: list[dict] = []
    for label, filter_id, original_filter, watermarked_filter in transforms:
        baseline = _decode_first_frame(original_path, original_filter)
        embedded = _decode_first_frame(watermarked_path, watermarked_filter)
        if filter_id == "reencode":
            baseline, embedded = _quantize(baseline), _quantize(embedded)
        recovered, confidence, bits_correct, bits_total = _extract_video_marker(baseline, embedded, width, height, marker)
        checks.append(
            {
                "filter": label,
                "filter_id": filter_id,
                "marker": marker,
                "recovered_marker": recovered,
                "confidence": round(confidence, 3),
                "bits_correct": bits_correct,
                "bits_total": bits_total,
                "confidence_method": "bits corretamente recuperados / 64 bits do sinal HMAC no primeiro frame real",
                "survives": confidence >= 0.9,
            }
        )
    baseline = _quantize(_decode_first_frame(original_path))
    embedded = _quantize(_decode_first_frame(watermarked_path))
    recovered, confidence, bits_correct, bits_total = _extract_video_marker(baseline, embedded, width, height, marker)
    checks.append(
        {
            "filter": "re-encode/quantização",
            "filter_id": "reencode",
            "marker": marker,
            "recovered_marker": recovered,
            "confidence": round(confidence, 3),
            "bits_correct": bits_correct,
            "bits_total": bits_total,
            "confidence_method": "bits corretamente recuperados / 64 bits do sinal HMAC após quantização 4 níveis",
            "survives": confidence >= 0.9,
        }
    )
    return checks
