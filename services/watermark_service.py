from __future__ import annotations

import threading
import time
import uuid

from models.entities import WatermarkClaim
from services.watermark_registry import WatermarkRegistry
from utils.image_watermark import detect_image, visual_marker
from utils.security import create_watermark_token, verify_watermark_token
from utils.video_watermark import detect_video


class WatermarkService:
    def __init__(self, secret_key: str, registry: WatermarkRegistry | None = None) -> None:
        self._secret_key = secret_key
        self._registry_store = registry or WatermarkRegistry()
        self._registry: dict[str, str] = {}
        self._registry_lock = threading.RLock()
        self._load_registry()

    def _load_registry(self) -> None:
        with self._registry_lock:
            self._registry = self._registry_store.load(self._secret_key)

    def configure(self, secret_key: str) -> None:
        self._secret_key = secret_key
        self._load_registry()

    @property
    def secret_key(self) -> str:
        return self._secret_key

    def issue(
        self,
        client_id: str,
        server_id: str,
        chunk_number: int,
        content_id: str | None = None,
    ) -> tuple[str, WatermarkClaim]:
        issued_at = time.time()
        chunk_id = f"chunk-{chunk_number:06d}-{uuid.uuid4().hex[:8]}"
        token = create_watermark_token(
            client_id,
            server_id,
            issued_at,
            chunk_id,
            self._secret_key,
            content_id,
        )
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
        """Index a valid token in memory and in the durable marker registry."""
        claim = self.verify(token)
        with self._registry_lock:
            marker = visual_marker(token)
            self._registry_store.put(self._secret_key, marker, token, claim.issued_at)
            self._registry[marker] = token
        return claim.to_dict()

    def detect_image(self, image) -> dict:
        return self._resolve_detection(detect_image(image, self._secret_key))

    def detect_video(
        self,
        path,
        adaptive: bool = True,
        algorithm: str = "adaptive-spread",
        dct_step: float = 10.0,
    ) -> dict:
        return self._resolve_detection(
            detect_video(path, self._secret_key, adaptive=adaptive, algorithm=algorithm, dct_step=dct_step)
        )

    def _resolve_detection(self, evidence: dict) -> dict:
        """Promote evidence only through exact marker association.

        A detector may produce a candidate after compression or another
        transformation. Hamming proximity is not identity proof, so an
        unregistered or altered marker remains an auditable, non-blocking
        candidate instead of being assigned to the nearest customer.
        """
        if evidence.get("status") != "CANDIDATE":
            return evidence

        marker = evidence.get("marker")
        with self._registry_lock:
            token = self._registry.get(marker) if isinstance(marker, str) else None

        if not token:
            return {
                **evidence,
                "status": "CANDIDATE",
                "authentication": "unregistered-marker",
                "reason": "marcador visual recuperado, mas sem associação exata registrada",
            }

        try:
            claim = self.verify(token)
        except ValueError as exc:
            return {
                **evidence,
                "status": "CANDIDATE",
                "authentication": "invalid-registered-claim",
                "reason": f"claim registrado inválido: {exc}",
            }

        if visual_marker(token) != marker:
            return {
                **evidence,
                "status": "CANDIDATE",
                "authentication": "marker-token-mismatch",
                "reason": "marcador não corresponde exatamente ao token registrado",
            }

        return {
            **evidence,
            "status": "VALID",
            "authentication": "exact-marker-and-cryptographic-claim",
            "claim": claim.to_dict(),
            "client_id": claim.client_id,
            "server_id": claim.server_id,
            "content_id": claim.content_id,
            "visual_hamming_distance": 0,
            "verification": "HMAC e AES-GCM verificados; marcador visual associado exatamente ao token registrado",
        }

    def registered_token_for_marker(self, marker: str | None) -> str | None:
        """Return a token only for an exact registered visual marker."""
        if not marker:
            return None
        with self._registry_lock:
            return self._registry.get(marker)
