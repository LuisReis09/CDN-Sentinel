from __future__ import annotations

import time
import uuid

from models.entities import WatermarkClaim
from utils.security import create_watermark_token, verify_watermark_token


class WatermarkService:
    def __init__(self, secret_key: str) -> None:
        self._secret_key = secret_key

    def configure(self, secret_key: str) -> None:
        self._secret_key = secret_key

    @property
    def secret_key(self) -> str:
        return self._secret_key

    def issue(self, client_id: str, server_id: str, chunk_number: int) -> tuple[str, WatermarkClaim]:
        issued_at = time.time()
        chunk_id = f"chunk-{chunk_number:06d}-{uuid.uuid4().hex[:8]}"
        token = create_watermark_token(client_id, server_id, issued_at, chunk_id, self._secret_key)
        claim = WatermarkClaim(
            client_id=client_id,
            server_id=server_id,
            issued_at=issued_at,
            chunk_id=chunk_id,
            signature=token.rsplit(".", 1)[1],
        )
        return token, claim

    def verify(self, token: str) -> WatermarkClaim:
        payload = verify_watermark_token(token, self._secret_key)
        return WatermarkClaim(
            client_id=payload["client_id"],
            server_id=payload["server_id"],
            issued_at=float(payload["issued_at"]),
            chunk_id=payload["chunk_id"],
            signature=payload["signature"],
        )

