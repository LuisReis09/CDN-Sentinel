from __future__ import annotations

import sqlite3
import threading
import time
import uuid

from models.entities import WatermarkClaim
from services.watermark_registry import WatermarkRegistry
from utils.image_watermark import detect_image, visual_marker
from utils.security import create_watermark_token, verify_watermark_token
from utils.video_watermark import detect_video
from watermark.claims import ClaimError, WatermarkClaim as ForensicClaim, create_claim_token, verify_claim_token


class WatermarkService:
    def __init__(self, secret_key: str, registry: WatermarkRegistry | None = None) -> None:
        self._secret_key = secret_key
        self._forensic_keys: dict[str, str] = {"primary": secret_key}
        self._active_key_id = "primary"
        self._registry_store = registry or WatermarkRegistry()
        self._registry: dict[str, str] = {}
        self._registry_lock = threading.RLock()
        self._load_registry()

    def _load_registry(self) -> None:
        with self._registry_lock:
            self._registry = self._registry_store.load(self._secret_key)

    def configure(self, secret_key: str) -> None:
        self._secret_key = secret_key
        self._forensic_keys["primary"] = secret_key
        self._active_key_id = "primary"
        self._load_registry()

    def rotate_key(self, key_id: str, secret_key: str, *, activate: bool = True) -> None:
        """Keep historical keys for verification after issuing with a new kid."""
        if not key_id or "." in key_id or len(key_id) > 80 or len(secret_key) < 16:
            raise ValueError("kid ou segredo inválido")
        if key_id in self._forensic_keys and self._forensic_keys[key_id] != secret_key:
            raise ValueError("kid já pertence a outra chave")
        with self._registry_lock:
            if key_id not in self._forensic_keys and len(self._forensic_keys) >= 8:
                raise ValueError("limite de oito chaves históricas")
            self._forensic_keys[key_id] = secret_key
            if activate:
                self._active_key_id = key_id

    @property
    def secret_key(self) -> str:
        return self._secret_key

    def visual_secret_for_token(self, token: str) -> str:
        if token.startswith("CDNWM4."):
            kid = token.split(".", 3)[1]
            if kid not in self._forensic_keys:
                raise ValueError("kid desconhecido")
            return self._forensic_keys[kid]
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

    def issue_forensic_claim(
        self,
        *,
        client_id: str,
        server_id: str,
        content_id: str,
        session_id: str | None = None,
        segment_range: str = "0-0",
        algorithm_id: str = "adaptive-spread-v5",
        fingerprint_scheme: str = "visual-marker-48-secded",
        key_id: str | None = None,
        valid_for_seconds: float = 86_400.0,
    ) -> tuple[str, ForensicClaim]:
        """Issue a CDNWM4 claim whose plaintext remains in the ledger only."""
        if not 1 <= valid_for_seconds <= 366 * 86_400:
            raise ValueError("valid_for_seconds fora do intervalo")
        now = time.time()
        key_id = key_id or self._active_key_id
        if key_id not in self._forensic_keys:
            raise ValueError("kid desconhecido")
        claim_secret = self._forensic_keys[key_id]
        def existing_session_claim() -> tuple[str, ForensicClaim] | None:
            if session_id is None:
                return None
            record = self._registry_store.claim_for_session(
                claim_secret, session_id, content_id, segment_range, algorithm_id, server_id,
            )
            if record is None:
                return None
            try:
                existing_claim = verify_claim_token(record["claim_token"], claim_secret)
            except ClaimError as exc:
                raise ValueError(f"claim da sessão não pode ser reutilizado: {exc}") from exc
            if existing_claim.to_dict() != record["claim"]:
                raise ValueError("claim da sessão diverge do token autenticado")
            if (
                existing_claim.client_id != client_id or existing_claim.server_id != server_id
                or existing_claim.fingerprint_scheme != fingerprint_scheme
            ):
                raise ValueError("sessão já vinculada a outra entrega")
            with self._registry_lock:
                self._registry[visual_marker(record["claim_token"])] = record["claim_token"]
            return record["claim_token"], existing_claim

        reused = existing_session_claim()
        if reused is not None:
            return reused
        watermark_id = uuid.uuid4().hex
        claim = ForensicClaim(
            version="CDNWM4", watermark_id=watermark_id,
            session_id=session_id or uuid.uuid4().hex,
            client_id=client_id, server_id=server_id, content_id=content_id,
            issued_at=now, valid_from=now - 30.0, valid_until=now + float(valid_for_seconds),
            algorithm_id=algorithm_id, key_id=key_id,
            fingerprint_scheme=fingerprint_scheme, segment_range=segment_range,
        )
        token = create_claim_token(claim, claim_secret)
        marker = visual_marker(token)
        try:
            self._registry_store.put_claim(claim_secret, marker, token, claim.to_dict())
        except sqlite3.IntegrityError:
            reused = existing_session_claim()
            if reused is None:
                raise
            return reused
        with self._registry_lock:
            self._registry[marker] = token
        return token, claim

    def verify(self, token: str) -> WatermarkClaim:
        if isinstance(token, str) and token.startswith("CDNWM4."):
            try:
                kid = token.split(".", 3)[1]
                if kid not in self._forensic_keys:
                    raise ClaimError("kid não disponível para verificação histórica")
                claim = verify_claim_token(token, self._forensic_keys[kid], allow_expired=True)
            except ClaimError as exc:
                raise ValueError(str(exc)) from exc
            return WatermarkClaim(
                client_id=claim.client_id, server_id=claim.server_id, issued_at=claim.issued_at,
                chunk_id=claim.segment_range, signature=token.rsplit(".", 1)[1], content_id=claim.content_id,
                version=claim.version, watermark_id=claim.watermark_id, session_id=claim.session_id,
                valid_from=claim.valid_from, valid_until=claim.valid_until, algorithm_id=claim.algorithm_id,
                key_id=claim.key_id, fingerprint_scheme=claim.fingerprint_scheme, segment_range=claim.segment_range,
            )
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

    def detect_forensic_video(self, path, *, algorithm: str = "auto", max_frames: int = 24) -> dict:
        """Detect a marker and resolve it only against the durable ledger."""
        algorithms = ("qim2", "adaptive-spread") if algorithm == "auto" else (algorithm,)
        if any(item not in {"qim2", "adaptive-spread", "dct"} for item in algorithms):
            raise ValueError("algoritmo visual desconhecido")
        strongest: dict | None = None
        for algorithm_name in algorithms:
            for secret in self._forensic_keys.values():
                evidence = detect_video(path, secret, algorithm=algorithm_name, max_frames=max_frames)
                if strongest is None or evidence.get("status") == "CANDIDATE":
                    strongest = evidence
                if evidence.get("status") != "CANDIDATE":
                    continue
                record = self._registry_store.claim_for_marker(secret, str(evidence.get("marker")))
                if not record:
                    continue
                if visual_marker(record["claim_token"]) != evidence.get("marker"):
                    continue
                try:
                    claim = self.verify(record["claim_token"])
                except ValueError:
                    continue
                algorithm_id = {"dct": "dct-qim-v1", "qim2": "dct-qim-v2", "adaptive-spread": "adaptive-spread-v5"}[algorithm_name]
                if claim.watermark_id != record["watermark_id"] or claim.algorithm_id != algorithm_id:
                    continue
                return {
                    **evidence, "forensic_status": "VALID", "authentication": "exact-marker-and-cryptographic-claim",
                    "attribution": "AUTHENTICATED", "claim": claim.to_dict(), "claim_hash": record["claim_hash"],
                    "algorithm_id": algorithm_id,
                }
        evidence = strongest or {"status": "NOT_FOUND"}
        if evidence.get("status") == "CANDIDATE":
            return {**evidence, "forensic_status": "CANDIDATE", "authentication": "unregistered-or-context-mismatch", "attribution": "NONE"}
        return {**evidence, "forensic_status": "INCONCLUSIVE" if evidence.get("status") == "INCONCLUSIVE" else "NOT_FOUND", "attribution": "NONE"}

    def register_token(self, token: str) -> dict:
        """Index a valid token in memory and in the durable marker registry."""
        claim = self.verify(token)
        with self._registry_lock:
            marker = visual_marker(token)
            secret = self._forensic_keys.get(claim.key_id or "primary", self._secret_key)
            self._registry_store.put(secret, marker, token, claim.issued_at)
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
