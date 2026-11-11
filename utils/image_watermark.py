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
DATA_BITS = 40
SYNC_BITS = 16
REPETITIONS = 3
SYNC_REPETITIONS = 3
DATA_REPETITIONS = 3
TOTAL_SLOTS = SYNC_BITS * SYNC_REPETITIONS + DATA_BITS * DATA_REPETITIONS
MIN_CELL_SIZE = 8
DEFAULT_STRENGTH = 12.0
CARRIER_BLOCK = 6
ADAPTIVE_MASK_FLOOR = 0.05
SYNC_MARKER = hashlib.sha256(b"CDN-Sentinel/image-watermark/sync-v3").hexdigest()[:4]


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
    """Return the 40-bit visual identifier derived from an authenticated token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:10]


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
    coarse_height = max(1, min(height, int(np.ceil(height / CARRIER_BLOCK))))
    coarse_width = max(1, min(width, int(np.ceil(width / CARRIER_BLOCK))))
    coarse = rng.choice(np.array([-1.0, 1.0], dtype=np.float32), size=(coarse_height, coarse_width))
    carrier = np.repeat(np.repeat(coarse, CARRIER_BLOCK, axis=0), CARRIER_BLOCK, axis=1)[:height, :width]
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


def _box_mean(values: np.ndarray, radius: int = 2) -> np.ndarray:
    """Return a bounded local mean without adding a numerical dependency."""
    if radius <= 0:
        return values.astype(np.float32, copy=True)
    height, width = values.shape
    padded = np.pad(values.astype(np.float64), ((radius, radius), (radius, radius)), mode="reflect")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant")
    integral = integral.cumsum(axis=0).cumsum(axis=1)
    size = 2 * radius + 1
    total = (
        integral[size:, size:]
        - integral[:-size, size:]
        - integral[size:, :-size]
        + integral[:-size, :-size]
    )
    return (total / float(size * size)).astype(np.float32)


def _perceptual_mask(luma: np.ndarray) -> np.ndarray:
    """Estimate where a small luminance perturbation is least noticeable.

    Texture masks the signal, while very dark regions receive less energy. The
    floor avoids starving a complete bit, and the detector recomputes the same
    mask from the received frame, so no original image is required.
    """
    mean = _box_mean(luma, radius=2)
    variance = np.maximum(_box_mean(luma * luma, radius=2) - mean * mean, 0.0)
    texture = np.sqrt(variance)
    texture_factor = np.clip((texture - 2.0) / 22.0, 0.0, 1.0)
    dark_factor = 0.35 + 0.65 * np.clip((luma - 12.0) / 96.0, 0.0, 1.0)
    mask = (ADAPTIVE_MASK_FLOOR + (1.0 - ADAPTIVE_MASK_FLOOR) * texture_factor) * dark_factor
    return np.clip(mask, ADAPTIVE_MASK_FLOOR * 0.65, 1.0).astype(np.float32)


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
    sync_bits = marker_bits(SYNC_MARKER, SYNC_BITS)
    data_bits = marker_bits(marker, DATA_BITS)
    return (
        [bit for bit in sync_bits for _ in range(SYNC_REPETITIONS)]
        + [bit for bit in data_bits for _ in range(DATA_REPETITIONS)]
    )


def embed_image(
    image: Image.Image,
    token: str,
    secret: str,
    strength: float = DEFAULT_STRENGTH,
    adaptive: bool = True,
) -> tuple[Image.Image, dict]:
    """Embed a keyed spread-spectrum marker without needing an original at detection time."""
    layout = _layout(image)
    before, _mode, _alpha = _luminance(image)
    after = before.copy()
    marker = visual_marker(token)
    mask = _perceptual_mask(before) if adaptive else np.ones_like(before, dtype=np.float32)
    slots = _slot_order(secret)
    for slot, bit in zip(slots, _expanded_bits(marker)):
        x0, y0, x1, y1 = _cell_bounds(layout, slot)
        carrier = _carrier(secret, slot, (y1 - y0, x1 - x0))
        weighted_carrier = carrier * mask[y0:y1, x0:x1]
        weighted_carrier -= float(weighted_carrier.mean())
        after[y0:y1, x0:x1] += (1.0 if bit else -1.0) * float(strength) * weighted_carrier
    return _rgb_delta(image, before, after), {
        "version": "CDNIMG4-ADAPTIVE-SPREAD",
        "marker": marker,
        "bits": DATA_BITS,
        "repetitions": REPETITIONS,
        "sync_repetitions": SYNC_REPETITIONS,
        "data_repetitions": DATA_REPETITIONS,
        "sync_bits": SYNC_BITS,
        "carrier_block": CARRIER_BLOCK,
        "grid": f"{GRID_SIZE}x{GRID_SIZE}",
        "layout": layout,
        "strength": float(strength),
        "adaptive": adaptive,
    }


def _decode_score_vector(scores: list[float] | np.ndarray, layout: ImageWatermarkLayout) -> dict:
    scores = list(float(score) for score in scores)
    bit_scores = []
    offset = 0
    for _index in range(SYNC_BITS):
        bit_scores.append(scores[offset:offset + SYNC_REPETITIONS])
        offset += SYNC_REPETITIONS
    for _index in range(DATA_BITS):
        bit_scores.append(scores[offset:offset + DATA_REPETITIONS])
        offset += DATA_REPETITIONS
    recovered = [int(sum(1 if score >= 0 else 0 for score in group) >= (len(group) / 2)) for group in bit_scores]
    consistency = [max(sum(score >= 0 for score in group), sum(score < 0 for score in group)) / len(group) for group in bit_scores if group]
    sync = recovered[:SYNC_BITS]
    data = recovered[SYNC_BITS:SYNC_BITS + DATA_BITS]
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


def _decode_scores(image: Image.Image, secret: str, adaptive: bool = True) -> dict:
    layout = _layout(image)
    luma, _mode, _alpha = _luminance(image)
    mask = _perceptual_mask(luma) if adaptive else np.ones_like(luma, dtype=np.float32)
    scores: list[float] = []
    slots = _slot_order(secret)
    for slot in slots:
        x0, y0, x1, y1 = _cell_bounds(layout, slot)
        tile = luma[y0:y1, x0:x1]
        carrier = _carrier(secret, slot, tile.shape)
        weighted_carrier = carrier * mask[y0:y1, x0:x1]
        weighted_carrier -= float(weighted_carrier.mean())
        centered = tile - float(tile.mean())
        scores.append(float(np.sum(centered * weighted_carrier)))

    return _decode_score_vector(scores, layout)


def classify_image_evidence(evidence: dict) -> dict:
    """Classify decoded evidence; video detection uses this after frame aggregation."""
    sync = float(evidence["sync_confidence"])
    consistency = float(evidence["repetition_consistency"])
    if sync < 0.5:
        status = "NOT_FOUND"
    elif sync < 0.65 or consistency < 0.70:
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


def detect_image(image: Image.Image, secret: str, adaptive: bool = True) -> dict:
    """Detect a candidate marker without an original image or expected token."""
    try:
        evidence = _decode_scores(image, secret, adaptive=adaptive)
    except ImageWatermarkUnsupported as exc:
        return {
            "status": "INCONCLUSIVE",
            "marker": None,
            "reason": str(exc),
            "supported": False,
            "confidence": 0.0,
        }
    return classify_image_evidence(evidence)
