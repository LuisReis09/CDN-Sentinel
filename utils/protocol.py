from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlparse


def canonical_body(payload: object | None) -> bytes:
    if payload is None:
        return b""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def signed_headers(secret: str, method: str, path: str, payload: object | None = None, *, nonce: str | None = None, timestamp: int | None = None) -> dict[str, str]:
    ts = int(time.time()) if timestamp is None else int(timestamp)
    message_nonce = nonce or uuid.uuid4().hex
    digest = hashlib.sha256(canonical_body(payload)).hexdigest()
    material = f"{ts}.{message_nonce}.{method.upper()}.{path}.{digest}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return {"X-CDN-Timestamp": str(ts), "X-CDN-Nonce": message_nonce, "X-CDN-Signature": signature}


def verify_headers(secret: str, method: str, path: str, payload: object | None, headers: object, seen_nonce, ttl_seconds: int = 30) -> tuple[bool, str]:
    try:
        timestamp = int(headers.get("X-CDN-Timestamp", ""))
        nonce = str(headers.get("X-CDN-Nonce", ""))
        signature = str(headers.get("X-CDN-Signature", ""))
    except (TypeError, ValueError):
        return False, "cabeçalhos de autenticação interna ausentes"
    if not nonce or abs(time.time() - timestamp) > ttl_seconds:
        return False, "mensagem interna expirada"
    expected = signed_headers(secret, method, path, payload, nonce=nonce, timestamp=timestamp)["X-CDN-Signature"]
    if not hmac.compare_digest(signature, expected):
        return False, "assinatura interna inválida"
    if not seen_nonce(nonce):
        return False, "nonce interno já utilizado"
    return True, "ok"


def path_from_url(url: str) -> str:
    return urlparse(url).path or "/"
