from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from typing import Any, Dict

from cryptography.exceptions import InvalidTag

from utils.crypto import decrypt_bytes, encrypt_bytes


def _encode(value: Dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> Dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8"))


def create_watermark_token(client_id: str, server_id: str, issued_at: float, chunk_id: str, secret_key: str) -> str:
    if not all(isinstance(value, str) and 1 <= len(value) <= 160 for value in (client_id, server_id, chunk_id)):
        raise ValueError("identificadores de watermark inválidos")
    payload = {
        "client_id": client_id,
        "server_id": server_id,
        "issued_at": round(issued_at, 6),
        "chunk_id": chunk_id,
    }
    plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    nonce, ciphertext = encrypt_bytes(plaintext, secret_key, aad="CDNWM2", context="watermark")
    encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
    signature = hmac.new(secret_key.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"CDNWM2.{encoded}.{signature}"


def verify_watermark_token(token: str, secret_key: str) -> Dict[str, Any]:
    try:
        version, encoded, signature = token.split(".", 2)
        if version not in {"CDNWM1", "CDNWM2"}:
            raise ValueError("versão de watermark inválida")
        expected = hmac.new(secret_key.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("assinatura HMAC inválida")
        if version == "CDNWM1":
            payload = _decode(encoded)
        else:
            padding = "=" * (-len(encoded) % 4)
            encrypted = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
            if len(encrypted) <= 12:
                raise ValueError("payload AES-GCM incompleto")
            plaintext = decrypt_bytes(encrypted[:12], encrypted[12:], secret_key, aad="CDNWM2", context="watermark")
            payload = json.loads(plaintext.decode("utf-8"))
        if not isinstance(payload, dict) or not all(isinstance(payload.get(key), str) and payload.get(key) for key in ("client_id", "server_id", "chunk_id")):
            raise ValueError("claim incompleto")
        if not isinstance(payload.get("issued_at"), (int, float)):
            raise ValueError("issued_at inválido")
        payload["signature"] = signature
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error, InvalidTag) as exc:
        raise ValueError(f"watermark inválida: {exc}") from exc


def watermark_encryption_metadata(token: str) -> Dict[str, Any]:
    """Expose non-secret AES-GCM envelope details for the laboratory UI."""

    version, encoded, _signature = token.split(".", 2)
    if version != "CDNWM2":
        return {"version": version, "algorithm": "HMAC-SHA256 legado", "encrypted": False}
    padding = "=" * (-len(encoded) % 4)
    encrypted = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
    nonce = encrypted[:12]
    ciphertext_with_tag = encrypted[12:]
    ciphertext, tag = ciphertext_with_tag[:-16], ciphertext_with_tag[-16:]
    return {
        "version": version,
        "algorithm": "AES-256-GCM + HMAC-SHA256",
        "encrypted": True,
        "aad": "CDNWM2",
        "nonce_base64url": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
        "ciphertext_base64url": base64.urlsafe_b64encode(ciphertext).decode("ascii").rstrip("="),
        "authentication_tag_base64url": base64.urlsafe_b64encode(tag).decode("ascii").rstrip("="),
    }

