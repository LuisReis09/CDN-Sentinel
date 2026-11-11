from __future__ import annotations

import time
import uuid
import threading

from models.entities import WatermarkClaim
from utils.image_watermark import detect_image, visual_marker
from utils.video_watermark import detect_video
from utils.security import create_watermark_token, verify_watermark_token


VISUAL_ASSOCIATION_MAX_HAMMING = 5


class WatermarkService:
    def __init__(self, secret_key: str) -> None:
        self._secret_key = secret_key
        self._registry: dict[str, str] = {}
        self._registry_lock = threading.RLock()

    def configure(self, secret_key: str) -> None:
        self._secret_key = secret_key
        with self._registry_lock:
            self._registry.clear()

    @property
    def secret_key(self) -> str:
        return self._secret_key

    def issue(self, client_id: str, server_id: str, chunk_number: int, content_id: str | None = None) -> tuple[str, WatermarkClaim]:
        issued_at = time.time()
        chunk_id = f"chunk-{chunk_number:06d}-{uuid.uuid4().hex[:8]}"
        token = create_watermark_token(client_id, server_id, issued_at, chunk_id, self._secret_key, content_id)
        claim = WatermarkClaim(
            client_id=client_id,
            server_id=server_id,
            issued_at=issued_at,
            chunk_id=chunk_id,
            signature=token.rsplit(".", 1)[1],
            content_id=content_id,
            version=token.split(".", 1)[0],
        )
        self.register_token(token)
        return token, claim

    def verify(self, token: str) -> WatermarkClaim:
        payload = verify_watermark_token(token, self._secret_key)
        return WatermarkClaim(
            client_id=payload["client_id"],
            server_id=payload["server_id"],
            issued_at=float(payload["issued_at"]),
            chunk_id=payload["chunk_id"],
            signature=payload["signature"],
            content_id=payload.get("content_id"),
            version=payload.get("version", "CDNWM2"),
        )

    def register_token(self, token: str) -> dict:
        """Index a valid token so visual evidence can be linked to a claim."""
        claim = self.verify(token)
        with self._registry_lock:
            self._registry[visual_marker(token)] = token
        return claim.to_dict()

    def detect_image(self, image) -> dict:
        return self._resolve_detection(detect_image(image, self._secret_key))

    def detect_video(self, path, adaptive: bool = True, algorithm: str = "adaptive-spread", dct_step: float = 10.0) -> dict:
        return self._resolve_detection(
            detect_video(path, self._secret_key, adaptive=adaptive, algorithm=algorithm, dct_step=dct_step)
        )

    def _resolve_detection(self, evidence: dict) -> dict:
        if evidence.get("status") != "CANDIDATE":
            return evidence
        marker = evidence.get("marker")
        with self._registry_lock:
            token = self._registry.get(str(marker))
            visual_distance = 0
            if not token and isinstance(marker, str):
                nearby: list[tuple[int, str]] = []
                for registered_marker, registered_token in self._registry.items():
                    if len(registered_marker) != len(marker):
                        continue
                    distance = sum(
                        (int(left, 16) ^ int(right, 16)).bit_count()
                        for left, right in zip(marker, registered_marker)
                    )
                    if distance <= VISUAL_ASSOCIATION_MAX_HAMMING:
                        nearby.append((distance, registered_token))
                if nearby:
                    nearby.sort(key=lambda item: item[0])
                    if len(nearby) == 1 or nearby[0][0] < nearby[1][0]:
                        visual_distance, token = nearby[0]
        if not token:
            return {
                **evidence,
                "status": "INVALID",
                "reason": "marcador visual recuperado, mas não existe claim registrado para esta CDN",
            }
        try:
            claim = self.verify(token)
        except ValueError as exc:
            return {**evidence, "status": "INVALID", "reason": f"claim registrado inválido: {exc}"}
        if visual_marker(token) != marker and visual_distance > VISUAL_ASSOCIATION_MAX_HAMMING:
            return {**evidence, "status": "INVALID", "reason": "marcador não corresponde ao token registrado"}
        return {
            **evidence,
            "status": "VALID",
            "claim": claim.to_dict(),
            "client_id": claim.client_id,
            "server_id": claim.server_id,
            "content_id": claim.content_id,
            "visual_hamming_distance": visual_distance,
            "verification": "HMAC e AES-GCM verificados; marcador visual associado ao token registrado",
        }

