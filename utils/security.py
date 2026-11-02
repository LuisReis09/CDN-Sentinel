from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Dict


def _encode(value: Dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> Dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8"))


def create_watermark_token(client_id: str, server_id: str, issued_at: float, chunk_id: str, secret_key: str) -> str:
    payload = {
        "client_id": client_id,
        "server_id": server_id,
        "issued_at": round(issued_at, 6),
        "chunk_id": chunk_id,
    }
    encoded = _encode(payload)
    signature = hmac.new(secret_key.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"CDNWM1.{encoded}.{signature}"


def verify_watermark_token(token: str, secret_key: str) -> Dict[str, Any]:
    try:
        version, encoded, signature = token.split(".", 2)
        if version != "CDNWM1":
            raise ValueError("versão de watermark inválida")
        expected = hmac.new(secret_key.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("assinatura HMAC inválida")
        payload = _decode(encoded)
        payload["signature"] = signature
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"watermark inválida: {exc}") from exc

