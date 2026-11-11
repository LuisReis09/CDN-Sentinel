"""Algorithm contracts and adapters used by the forensic pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from PIL import Image

from utils.dct_watermark import detect_image_dct, embed_image_dct
from utils.image_watermark import detect_image, embed_image
from utils.qim_watermark import QIM_STEP, detect_image_qim, embed_image_qim


class WatermarkEmbedder(ABC):
    algorithm_id: str

    @abstractmethod
    def embed(self, media: Image.Image, payload: str, config: dict[str, Any] | None = None) -> tuple[Image.Image, dict[str, Any]]:
        raise NotImplementedError


class WatermarkExtractor(ABC):
    algorithm_id: str

    @abstractmethod
    def detect(self, media: Image.Image, config: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError


class DCTQIMEmbedder(WatermarkEmbedder, WatermarkExtractor):
    algorithm_id = "dct-qim-v1"

    def __init__(self, secret: str, step: float = 10.0) -> None:
        self.secret, self.step = secret, float(step)

    def embed(self, media: Image.Image, payload: str, config: dict[str, Any] | None = None) -> tuple[Image.Image, dict[str, Any]]:
        return embed_image_dct(media, payload, self.secret, step=float((config or {}).get("step", self.step)))

    def detect(self, media: Image.Image, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return detect_image_dct(media, self.secret, step=float((config or {}).get("step", self.step)))


class AdaptiveSpreadEmbedder(WatermarkEmbedder, WatermarkExtractor):
    algorithm_id = "adaptive-spread-v5"

    def __init__(self, secret: str, strength: float = 12.0) -> None:
        self.secret, self.strength = secret, float(strength)

    def embed(self, media: Image.Image, payload: str, config: dict[str, Any] | None = None) -> tuple[Image.Image, dict[str, Any]]:
        options = config or {}
        return embed_image(media, payload, self.secret, strength=float(options.get("strength", self.strength)), adaptive=bool(options.get("adaptive", True)))

    def detect(self, media: Image.Image, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return detect_image(media, self.secret, adaptive=bool((config or {}).get("adaptive", True)))


class DistributedQIMEmbedder(WatermarkEmbedder, WatermarkExtractor):
    algorithm_id = "dct-qim-v2"

    def __init__(self, secret: str, step: float = QIM_STEP) -> None:
        self.secret, self.step = secret, float(step)

    def embed(self, media: Image.Image, payload: str, config: dict[str, Any] | None = None) -> tuple[Image.Image, dict[str, Any]]:
        return embed_image_qim(media, payload, self.secret, step=float((config or {}).get("step", self.step)))

    def detect(self, media: Image.Image, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return detect_image_qim(media, self.secret, step=float((config or {}).get("step", self.step)))


class NeuralWatermarkAdapter:
    """Optional VideoSeal/PixelSeal adapter.

    The import is intentionally lazy: a CPU-only installation remains fully
    usable and reports an explicit unavailable state instead of silently
    substituting a mock.
    """

    def __init__(self, model_name: str = "videoseal") -> None:
        self.model_name = model_name

    def availability(self) -> dict[str, Any]:
        try:
            import videoseal  # type: ignore
            import torch  # type: ignore
        except ImportError as exc:
            return {"available": False, "model": self.model_name, "reason": f"dependência opcional ausente: {exc.name or exc}"}
        return {"available": True, "model": self.model_name, "torch_version": getattr(torch, "__version__", "unknown"), "implementation": "lazy-videoseal-adapter"}

    def embed(self, media: Any, payload_bits: Any, config: dict[str, Any] | None = None) -> Any:
        status = self.availability()
        if not status["available"]:
            raise RuntimeError(status["reason"])
        import videoseal  # type: ignore
        model = videoseal.load(self.model_name)
        return model.embed(media, is_video=getattr(media, "ndim", 0) == 4, msgs=payload_bits)
