"""Vectorized keyed DCT/QIM image watermark with spatial repetition.

Unlike the historical DCT experiment (one 8x8 block per coded slot), this
variant distributes every bit across many keyed blocks.  It carries 48 visual
bits plus 8 synchronization bits.  The 48-bit collision bound and perceptual
quality are measured separately; neither is claimed to be production ready.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np
from PIL import Image
from scipy.fft import dctn, idctn

from utils.image_watermark import DATA_BITS, SYNC_BITS, SYNC_MARKER, _luminance, _rgb_delta, marker_bits, visual_marker


QIM_STEP = 20.0
QIM_MIN_CORRELATION = 0.15
QIM_WIDTH = 640
QIM_BLOCK = 8
QIM_BITS = DATA_BITS + SYNC_BITS
PAIR = ((1, 2), (2, 1))


def _canonical(image: Image.Image) -> tuple[Image.Image, int, int]:
    width = QIM_WIDTH
    height = max(QIM_BLOCK, round(image.height * width / image.width))
    height = max(QIM_BLOCK, (height // QIM_BLOCK) * QIM_BLOCK)
    if image.width < 128 or image.height < 128:
        raise ValueError("mídia pequena demais para QIM")
    return image.convert("RGB").resize((width, height), Image.Resampling.BICUBIC), width, height


def _blocks(luma: np.ndarray) -> tuple[np.ndarray, int, int]:
    height, width = luma.shape
    rows, cols = height // QIM_BLOCK, width // QIM_BLOCK
    blocks = luma.reshape(rows, QIM_BLOCK, cols, QIM_BLOCK).transpose(0, 2, 1, 3)
    return blocks, rows, cols


def _order(secret: str, rows: int, cols: int) -> tuple[np.ndarray, np.ndarray]:
    digest = hashlib.sha256(f"CDN-Sentinel/qim-v2/{rows}x{cols}/{secret}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    order = rng.permutation(rows * cols)
    flips = rng.integers(0, 2, size=rows * cols, dtype=np.uint8)
    return order, flips


def _encoded_bits(marker: str) -> np.ndarray:
    return np.asarray(marker_bits(SYNC_MARKER, SYNC_BITS) + marker_bits(marker, DATA_BITS), dtype=np.uint8)


def _decode_score_vector(scores: np.ndarray) -> dict:
    expected_sync = marker_bits(SYNC_MARKER, SYNC_BITS)
    recovered = (scores < 0).astype(np.uint8)
    sync_correct = sum(int(a == b) for a, b in zip(recovered[:SYNC_BITS], expected_sync))
    bits = recovered[SYNC_BITS:].tolist()
    marker_bytes = bytes(sum(bits[i + j] << j for j in range(8)) for i in range(0, DATA_BITS, 8))
    # Even a strong visual candidate still needs exact marker + authenticated
    # claim association; these local gates are deliberately conservative.
    mean_strength = float(np.mean(np.abs(scores)))
    status = "CANDIDATE" if sync_correct >= 7 and mean_strength >= QIM_MIN_CORRELATION else ("NOT_FOUND" if sync_correct < 5 else "INCONCLUSIVE")
    return {
        "status": status, "marker": marker_bytes.hex(), "sync_confidence": sync_correct / SYNC_BITS,
        "confidence": round(mean_strength, 4), "confidence_kind": "uncalibrated-mean-qim-correlation",
        "mean_signal": round(mean_strength, 4), "scores": scores.tolist(), "supported": True,
    }


def embed_image_qim(image: Image.Image, token: str, secret: str, step: float = QIM_STEP) -> tuple[Image.Image, dict]:
    if step <= 0 or step > 40:
        raise ValueError("passo QIM fora do intervalo")
    canonical, width, height = _canonical(image)
    luma, _mode, _alpha = _luminance(canonical)
    blocks, rows, cols = _blocks(luma)
    coefficients = dctn(blocks.astype(np.float64) - 128.0, axes=(-2, -1), norm="ortho").reshape(rows * cols, 8, 8)
    order, flips = _order(secret, rows, cols)
    count = len(order)
    if count < QIM_BITS * 8:
        raise ValueError("menos de oito repetições por bit QIM")
    marker = visual_marker(token)
    bits = _encoded_bits(marker)
    indices = np.arange(count) % QIM_BITS
    carried = np.bitwise_xor(bits[indices], flips)
    left, right = PAIR
    selected = coefficients[order]
    difference = selected[:, left[0], left[1]] - selected[:, right[0], right[1]]
    target = np.rint((difference - carried * step) / (2 * step)) * (2 * step) + carried * step
    adjustment = (target - difference) * 0.5
    coefficients[order, left[0], left[1]] += adjustment
    coefficients[order, right[0], right[1]] -= adjustment
    transformed = idctn(coefficients.reshape(rows, cols, 8, 8), axes=(-2, -1), norm="ortho") + 128.0
    watermarked_luma = transformed.transpose(0, 2, 1, 3).reshape(height, width)
    residual = watermarked_luma - luma
    resized_residual = np.asarray(Image.fromarray(residual.astype(np.float32), mode="F").resize(image.size, Image.Resampling.BICUBIC), dtype=np.float32)
    original_luma, _mode, _alpha = _luminance(image)
    result = _rgb_delta(image, original_luma, original_luma + resized_residual)
    return result, {"version": "CDNIMG-QIM2", "marker": marker, "bits": DATA_BITS, "sync_bits": SYNC_BITS, "spatial_repetitions_min": count // QIM_BITS, "canonical_size": [width, height], "step": step}


def detect_image_qim(image: Image.Image, secret: str, step: float = QIM_STEP) -> dict:
    try:
        canonical, width, height = _canonical(image)
        luma, _mode, _alpha = _luminance(canonical)
        blocks, rows, cols = _blocks(luma)
        coefficients = dctn(blocks.astype(np.float64) - 128.0, axes=(-2, -1), norm="ortho").reshape(rows * cols, 8, 8)
        order, flips = _order(secret, rows, cols)
        if len(order) < QIM_BITS * 8:
            raise ValueError("menos de oito repetições por bit QIM")
        left, right = PAIR
        difference = coefficients[order, left[0], left[1]] - coefficients[order, right[0], right[1]]
        correlations = np.cos(np.pi * difference / step) * (1 - 2 * flips.astype(np.int8))
        scores = np.bincount(np.arange(len(order)) % QIM_BITS, weights=correlations, minlength=QIM_BITS) / np.bincount(np.arange(len(order)) % QIM_BITS, minlength=QIM_BITS)
        return {**_decode_score_vector(scores), "canonical_size": [width, height], "step": step, "spatial_repetitions_min": len(order) // QIM_BITS}
    except ValueError as exc:
        return {"status": "INCONCLUSIVE", "marker": None, "reason": str(exc), "supported": False, "confidence": 0.0}
