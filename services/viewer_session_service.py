"""Operator-issued viewer grants for the optional authenticated data plane.

This is a local simulator trust boundary: a configured operator grants a
short-lived token to a viewer after account authentication has happened
outside this application.  It does not claim to implement an identity provider.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


VERSION = "CDNVIEW1"


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


class ViewerSessionService:
    def __init__(self, secret: str) -> None:
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError("CDN_VIEWER_SESSION_SECRET deve conter material aleatório de pelo menos 32 caracteres")
        self._key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None,
            info=b"CDN-Sentinel/viewer-grant/CDNVIEW1",
        ).derive(secret.encode("utf-8"))

    def issue(self, client_id: str, content_id: str, simulation_id: str, *, ttl_seconds: int = 900) -> dict:
        if not client_id or not content_id or not simulation_id:
            raise ValueError("cliente, conteúdo e simulação são obrigatórios")
        if not 60 <= ttl_seconds <= 86_400:
            raise ValueError("ttl_seconds deve estar entre 60 e 86400")
        now = int(time.time())
        payload = {
            "version": VERSION, "session_id": f"view-{secrets.token_hex(16)}",
            "client_id": client_id, "content_id": content_id,
            "simulation_id": simulation_id, "issued_at": now,
            "valid_until": now + ttl_seconds,
        }
        encoded = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        mac = hmac.new(self._key, f"{VERSION}.{encoded}".encode("ascii"), hashlib.sha256).hexdigest()
        return {**payload, "token": f"{VERSION}.{encoded}.{mac}"}

    def verify(self, token: str, client_id: str, content_id: str, simulation_id: str, *, now: int | None = None) -> dict:
        if not isinstance(token, str) or len(token) > 2048:
            raise PermissionError("credencial de espectador ausente ou inválida")
        try:
            version, encoded, mac = token.split(".")
            if version != VERSION or len(mac) != 64:
                raise ValueError("formato inválido")
            expected = hmac.new(self._key, f"{version}.{encoded}".encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(mac, expected):
                raise ValueError("assinatura inválida")
            payload = json.loads(_decode(encoded))
            if not isinstance(payload, dict):
                raise ValueError("payload inválido")
            current = int(time.time()) if now is None else int(now)
            if (
                payload.get("version") != VERSION
                or payload.get("client_id") != client_id
                or payload.get("content_id") != content_id
                or payload.get("simulation_id") != simulation_id
                or not isinstance(payload.get("session_id"), str)
                or not payload["session_id"].startswith("view-")
                or not isinstance(payload.get("issued_at"), int)
                or not isinstance(payload.get("valid_until"), int)
                or payload["issued_at"] > current + 30
                or payload["valid_until"] < current
                or payload["valid_until"] - payload["issued_at"] > 86_400
            ):
                raise ValueError("vínculo ou validade inválidos")
            return payload
        except (ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error) as exc:
            raise PermissionError("credencial de espectador ausente, expirada ou incompatível") from exc
