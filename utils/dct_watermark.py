"""Keyed mid-frequency DCT watermark for imperceptible image experiments."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from utils.image_watermark import (
    ImageWatermarkUnsupported,
    SYNC_BITS,
    SYNC_MARKER,
    DATA_BITS,
    REPETITIONS,
    TOTAL_SLOTS,
    _expanded_bits,
    _decode_score_vector,
    _luminance,
    _rgb_delta,
    classify_image_evidence,
    marker_bits,
    visual_marker,
)


DCT_BLOCK = 8
DCT_MIN_SIZE = 128
DCT_STEP = 10.0
DCT_COEFFICIENTS = ((1, 2), (2, 1))


@dataclass(frozen=True)
class DCTWatermarkLayout:
    width: int
    height: int
    cell_width: int
    cell_height: int
    blocks_x: int
    blocks_y: int
    slots: int


@lru_cache(maxsize=1)
def _dct_matrix() -> np.ndarray:
    n = DCT_BLOCK
    matrix = np.zeros((n, n), dtype=np.float64)
    for u in range(n):
        alpha = np.sqrt(1.0 / n) if u == 0 else np.sqrt(2.0 / n)
        for x in range(n):
            matrix[u, x] = alpha * np.cos(np.pi * (2 * x + 1) * u / (2 * n))
    return matrix


def _dct(block: np.ndarray) -> np.ndarray:
    matrix = _dct_matrix()
    return matrix @ block @ matrix.T


def _idct(coefficients: np.ndarray) -> np.ndarray:
    matrix = _dct_matrix()
    return matrix.T @ coefficients @ matrix


def _layout(image: Image.Image) -> DCTWatermarkLayout:
    width, height = image.size
    blocks_x = width // DCT_BLOCK
    blocks_y = height // DCT_BLOCK
    slots = min(TOTAL_SLOTS, blocks_x * blocks_y)
    if min(width, height) < DCT_MIN_SIZE or slots < TOTAL_SLOTS:
        raise ImageWatermarkUnsupported(
            f"imagem {width}x{height} insuficiente para watermark DCT: são necessários pelo menos {DCT_MIN_SIZE}x{DCT_MIN_SIZE} pixels"
        )
    return DCTWatermarkLayout(width, height, DCT_BLOCK, DCT_BLOCK, blocks_x, blocks_y, slots)


def _block_order(secret: str, layout: DCTWatermarkLayout) -> list[int]:
    seed = int.from_bytes(
        hashlib.sha256(
            f"CDN-Sentinel/image-watermark/dct-slots\x00{secret}\x00{layout.blocks_x}x{layout.blocks_y}".encode("utf-8")
        ).digest()[:8],
        "big",
    )
    rng = np.random.default_rng(seed)
    order = np.arange(layout.blocks_x * layout.blocks_y)
    rng.shuffle(order)
    return [int(value) for value in order[:layout.slots]]


def _block_bounds(layout: DCTWatermarkLayout, index: int) -> tuple[int, int, int, int]:
    row, col = divmod(index, layout.blocks_x)
    x0, y0 = col * DCT_BLOCK, row * DCT_BLOCK
    return x0, y0, x0 + DCT_BLOCK, y0 + DCT_BLOCK


def _bits(marker: str) -> list[int]:
    return _expanded_bits(marker)


def _phase_difference(value: float, step: float) -> float:
    return ((value + step) % (2.0 * step)) - step


def embed_image_dct(image: Image.Image, token: str, secret: str, step: float = DCT_STEP) -> tuple[Image.Image, dict]:
    """Embed bits by quantizing a pair of mid-frequency DCT coefficients."""
    layout = _layout(image)
    before, _mode, _alpha = _luminance(image)
    after = before.copy()
    marker = visual_marker(token)
    for slot, bit in zip(_block_order(secret, layout), _bits(marker)):
        x0, y0, x1, y1 = _block_bounds(layout, slot)
        coefficients = _dct(before[y0:y1, x0:x1] - 128.0)
        left, right = DCT_COEFFICIENTS
        difference = float(coefficients[left] - coefficients[right])
        base = 2.0 * step * round(difference / (2.0 * step))
        target = base + (step * 0.5 if bit else -step * 0.5)
        adjustment = target - difference
        coefficients[left] += adjustment * 0.5
        coefficients[right] -= adjustment * 0.5
        after[y0:y1, x0:x1] = _idct(coefficients) + 128.0
    return _rgb_delta(image, before, after), {
        "version": "CDNIMG-DCT1",
        "marker": marker,
        "bits": DATA_BITS,
        "repetitions": REPETITIONS,
        "sync_bits": SYNC_BITS,
        "block": DCT_BLOCK,
        "coefficients": [list(item) for item in DCT_COEFFICIENTS],
        "step": float(step),
        "layout": layout,
    }


def _decode_scores(image: Image.Image, secret: str, step: float = DCT_STEP) -> dict:
    layout = _layout(image)
    luma, _mode, _alpha = _luminance(image)
    scores: list[float] = []
    left, right = DCT_COEFFICIENTS
    for slot in _block_order(secret, layout):
        x0, y0, x1, y1 = _block_bounds(layout, slot)
        coefficients = _dct(luma[y0:y1, x0:x1] - 128.0)
        scores.append(_phase_difference(float(coefficients[left] - coefficients[right]), step))
    return _decode_score_vector(scores, layout)


def detect_image_dct(image: Image.Image, secret: str, step: float = DCT_STEP) -> dict:
    """Detect DCT evidence without an original image or expected marker."""
    try:
        evidence = _decode_scores(image, secret, step=step)
    except ImageWatermarkUnsupported as exc:
        return {
            "status": "INCONCLUSIVE",
            "marker": None,
            "reason": str(exc),
            "supported": False,
            "confidence": 0.0,
        }
    return classify_image_evidence(evidence)
