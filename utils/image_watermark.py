"""Keyed, self-synchronizing visual watermark for still images.

The visual channel deliberately carries only a short authenticated marker. The
encrypted claim remains in the backend registry/token, so visual detection and
cryptographic verification are separate decisions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
from PIL import Image


GRID_SIZE = 16
DATA_BITS = 48
SYNC_BITS = 32
REPETITIONS = 3
TOTAL_SLOTS = (DATA_BITS + SYNC_BITS) * REPETITIONS
MIN_CELL_SIZE = 8
DEFAULT_STRENGTH = 8.0
SYNC_MARKER = hashlib.sha256(b"CDN-Sentinel/image-watermark/sync-v2").hexdigest()[:8]


class ImageWatermarkUnsupported(ValueError):
    """Raised when an image is too small to carry a reliable watermark."""


@dataclass(frozen=True)
class ImageWatermarkLayout:
    width: int
    height: int
    cell_width: int
    cell_height: int
    slots: int = TOTAL_SLOTS


def visual_marker(token: str) -> str:
    """Return the 48-bit visual identifier derived from an authenticated token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def marker_bits(marker: str, width: int = DATA_BITS) -> list[int]:
    raw = bytes.fromhex(marker[: max(2, width // 4)].ljust(max(2, width // 4), "0"))
    return [(byte >> bit) & 1 for byte in raw for bit in range(8)][:width]


def _layout(image: Image.Image) -> ImageWatermarkLayout:
    width, height = image.size
    cell_width = width // GRID_SIZE
    cell_height = height // GRID_SIZE
    if min(cell_width, cell_height) < MIN_CELL_SIZE:
        raise ImageWatermarkUnsupported(
            f"imagem {width}x{height} insuficiente: o detector precisa de pelo menos "
            f"{GRID_SIZE * MIN_CELL_SIZE}x{GRID_SIZE * MIN_CELL_SIZE} pixels"
        )
    return ImageWatermarkLayout(width, height, cell_width, cell_height)


def _slot_order(secret: str) -> list[int]:
    seed = int.from_bytes(
        hashlib.sha256(f"CDN-Sentinel/image-watermark/slots\x00{secret}".encode("utf-8")).digest()[:8],
        "big",
    )
    rng = np.random.default_rng(seed)
    order = np.arange(GRID_SIZE * GRID_SIZE)
    rng.shuffle(order)
    return [int(value) for value in order[:TOTAL_SLOTS]]


def _carrier(secret: str, slot: int, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    seed = int.from_bytes(
        hashlib.sha256(f"CDN-Sentinel/image-watermark/carrier\x00{secret}\x00{slot}".encode("utf-8")).digest()[:8],
        "big",
    )
    rng = np.random.default_rng(seed)
    # Use a low-frequency keyed pattern instead of independent pixel noise.
    # That keeps the signal measurable after a light blur or a resize/re-encode
    # while remaining visually noise-like without the secret key.
    coarse_height = max(1, min(height, int(np.ceil(height / 4))))
    coarse_width = max(1, min(width, int(np.ceil(width / 4))))
    coarse = rng.choice(np.array([-1.0, 1.0], dtype=np.float32), size=(coarse_height, coarse_width))
    carrier = np.repeat(np.repeat(coarse, 4, axis=0), 4, axis=1)[:height, :width]
    carrier -= float(carrier.mean())
    return carrier


def _luminance(image: Image.Image) -> tuple[np.ndarray, str, np.ndarray | None]:
    rgba = image.convert("RGBA")
    array = np.asarray(rgba, dtype=np.float32)
    alpha = array[:, :, 3].copy()
    rgb = array[:, :, :3]
    luma = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    return luma, image.mode, alpha


def _rebuild(luma: np.ndarray, original_mode: str, alpha: np.ndarray | None) -> Image.Image:
    clipped = np.clip(luma, 0.0, 255.0)
    # Apply the luminance delta proportionally to RGB so the visual signal does
    # not introduce a strong hue shift during RGB/YUV conversion.
    rgb = np.repeat(clipped[:, :, None], 3, axis=2)
    if alpha is not None:
        # The original luminance is not available here; preserving alpha is the
        # important property for RGBA. The caller supplies RGB-equivalent data.
        rgba = np.concatenate([rgb, alpha[:, :, None]], axis=2)
        return Image.fromarray(np.rint(rgba).astype(np.uint8), "RGBA").convert(original_mode)
    return Image.fromarray(np.rint(rgb).astype(np.uint8), "RGB").convert(original_mode)


def _rgb_delta(image: Image.Image, luma_before: np.ndarray, luma_after: np.ndarray) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32)
    delta = luma_after - luma_before
    rgb = np.clip(rgba[:, :, :3] + delta[:, :, None], 0.0, 255.0)
    output = np.concatenate([rgb, rgba[:, :, 3:4]], axis=2)
    if image.mode == "RGBA":
        return Image.fromarray(np.rint(output).astype(np.uint8), "RGBA")
    if image.mode == "L":
        return Image.fromarray(np.rint(np.clip(luma_after, 0.0, 255.0)).astype(np.uint8), "L")
    return Image.fromarray(np.rint(output[:, :, :3]).astype(np.uint8), "RGB").convert(image.mode)


def _cell_bounds(layout: ImageWatermarkLayout, cell_index: int) -> tuple[int, int, int, int]:
    row, col = divmod(cell_index, GRID_SIZE)
    x0 = col * layout.cell_width
    y0 = row * layout.cell_height
    x1 = layout.width if col == GRID_SIZE - 1 else (col + 1) * layout.cell_width
    y1 = layout.height if row == GRID_SIZE - 1 else (row + 1) * layout.cell_height
    return x0, y0, x1, y1


def _bits_for_payload(marker: str) -> list[int]:
    return marker_bits(SYNC_MARKER, SYNC_BITS) + marker_bits(marker, DATA_BITS)


def _expanded_bits(marker: str) -> list[int]:
    bits = _bits_for_payload(marker)
    return [bit for bit in bits for _ in range(REPETITIONS)]


def embed_image(image: Image.Image, token: str, secret: str, strength: float = DEFAULT_STRENGTH) -> tuple[Image.Image, dict]:
    """Embed a keyed spread-spectrum marker without needing an original at detection time."""
    layout = _layout(image)
    before, _mode, _alpha = _luminance(image)
    after = before.copy()
    marker = visual_marker(token)
    slots = _slot_order(secret)
    for slot, bit in zip(slots, _expanded_bits(marker)):
        x0, y0, x1, y1 = _cell_bounds(layout, slot)
        carrier = _carrier(secret, slot, (y1 - y0, x1 - x0))
        after[y0:y1, x0:x1] += (1.0 if bit else -1.0) * float(strength) * carrier
    return _rgb_delta(image, before, after), {
        "version": "CDNIMG2",
        "marker": marker,
        "bits": DATA_BITS,
        "repetitions": REPETITIONS,
        "sync_bits": SYNC_BITS,
        "grid": f"{GRID_SIZE}x{GRID_SIZE}",
        "layout": layout,
        "strength": float(strength),
    }


def _decode_score_vector(scores: list[float] | np.ndarray, layout: ImageWatermarkLayout) -> dict:
    scores = list(float(score) for score in scores)
    bit_scores = []
    for start in range(0, len(scores), REPETITIONS):
        bit_scores.append(scores[start:start + REPETITIONS])
    recovered = [int(sum(1 if score >= 0 else 0 for score in group) >= (REPETITIONS / 2)) for group in bit_scores]
    consistency = [max(sum(score >= 0 for score in group), sum(score < 0 for score in group)) / len(group) for group in bit_scores]
    sync = recovered[:SYNC_BITS]
    data = recovered[SYNC_BITS:]
    sync_expected = marker_bits(SYNC_MARKER, SYNC_BITS)
    sync_confidence = sum(int(actual == expected) for actual, expected in zip(sync, sync_expected)) / SYNC_BITS
    data_marker_bytes = bytearray()
    for index in range(0, len(data), 8):
        data_marker_bytes.append(sum(data[index + bit] << bit for bit in range(8)))
    marker = data_marker_bytes.hex()
    return {
        "marker": marker,
        "sync_confidence": round(sync_confidence, 4),
        "repetition_consistency": round(float(sum(consistency) / len(consistency)), 4),
        "mean_signal": round(float(np.mean(np.abs(scores))), 4),
        "scores": scores,
        "supported": True,
        "layout": layout,
    }


def _decode_scores(image: Image.Image, secret: str) -> dict:
    layout = _layout(image)
    luma, _mode, _alpha = _luminance(image)
    scores: list[float] = []
    for slot in _slot_order(secret):
        x0, y0, x1, y1 = _cell_bounds(layout, slot)
        tile = luma[y0:y1, x0:x1]
        carrier = _carrier(secret, slot, tile.shape)
        centered = tile - float(tile.mean())
        scores.append(float(np.sum(centered * carrier)))

    return _decode_score_vector(scores, layout)


def classify_image_evidence(evidence: dict) -> dict:
    """Classify decoded evidence; video detection uses this after frame aggregation."""
    sync = float(evidence["sync_confidence"])
    consistency = float(evidence["repetition_consistency"])
    if sync < 0.5:
        status = "NOT_FOUND"
    elif sync < 0.8 or consistency < 0.75:
        status = "INCONCLUSIVE"
    else:
        status = "CANDIDATE"
    confidence = round(0.65 * sync + 0.35 * consistency, 4)
    layout = evidence["layout"]
    return {
        "status": status,
        "marker": evidence["marker"],
        "sync_confidence": sync,
        "repetition_consistency": consistency,
        "mean_signal": evidence["mean_signal"],
        "confidence": confidence,
        "supported": True,
        "layout": {
            "width": layout.width,
            "height": layout.height,
            "cell_width": layout.cell_width,
            "cell_height": layout.cell_height,
            "slots": layout.slots,
        },
    }


def detect_image(image: Image.Image, secret: str) -> dict:
    """Detect a candidate marker without an original image or expected token."""
    try:
        evidence = _decode_scores(image, secret)
    except ImageWatermarkUnsupported as exc:
        return {
            "status": "INCONCLUSIVE",
            "marker": None,
            "reason": str(exc),
            "supported": False,
            "confidence": 0.0,
        }
    return classify_image_evidence(evidence)
