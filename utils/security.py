from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from typing import Any, Dict

from cryptography.exceptions import InvalidTag

from utils.crypto import decrypt_bytes, derive_key, encrypt_bytes


def _watermark_signature_key(secret_key: str, version: str) -> bytes:
    return secret_key.encode("utf-8") if version in {"CDNWM1", "CDNWM2"} else derive_key(secret_key, "watermark-signing-v3")


def _encode(value: Dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> Dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8"))


def create_watermark_token(
    client_id: str,
    server_id: str,
    issued_at: float,
    chunk_id: str,
    secret_key: str,
    content_id: str | None = None,
) -> str:
    if not all(isinstance(value, str) and 1 <= len(value) <= 160 for value in (client_id, server_id, chunk_id)):
        raise ValueError("identificadores de watermark inválidos")
    version = "CDNWM3" if content_id else "CDNWM2"
    payload = {
        "client_id": client_id,
        "server_id": server_id,
        "issued_at": round(issued_at, 6),
        "chunk_id": chunk_id,
    }
    if content_id:
        if not isinstance(content_id, str) or not 1 <= len(content_id) <= 240:
            raise ValueError("content_id de watermark inválido")
        payload["content_id"] = content_id
    plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    aad = version
    context = "watermark" if version == "CDNWM2" else "watermark-v3"
    nonce, ciphertext = encrypt_bytes(plaintext, secret_key, aad=aad, context=context)
    encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
    signature = hmac.new(_watermark_signature_key(secret_key, version), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{version}.{encoded}.{signature}"


def verify_watermark_token(token: str, secret_key: str) -> Dict[str, Any]:
    try:
        version, encoded, signature = token.split(".", 2)
        if version not in {"CDNWM1", "CDNWM2", "CDNWM3"}:
            raise ValueError("versão de watermark inválida")
        expected = hmac.new(_watermark_signature_key(secret_key, version), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("assinatura HMAC inválida")
        if version == "CDNWM1":
            payload = _decode(encoded)
        else:
            padding = "=" * (-len(encoded) % 4)
            encrypted = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
            if len(encrypted) <= 12:
                raise ValueError("payload AES-GCM incompleto")
            aad = version
            context = "watermark" if version == "CDNWM2" else "watermark-v3"
            plaintext = decrypt_bytes(encrypted[:12], encrypted[12:], secret_key, aad=aad, context=context)
            payload = json.loads(plaintext.decode("utf-8"))
        if not isinstance(payload, dict) or not all(isinstance(payload.get(key), str) and payload.get(key) for key in ("client_id", "server_id", "chunk_id")):
            raise ValueError("claim incompleto")
        if not isinstance(payload.get("issued_at"), (int, float)):
            raise ValueError("issued_at inválido")
        if version == "CDNWM3" and not isinstance(payload.get("content_id"), str):
            raise ValueError("content_id ausente no claim CDNWM3")
        payload["signature"] = signature
        payload["version"] = version
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error, InvalidTag) as exc:
        raise ValueError(f"watermark inválida: {exc}") from exc


def watermark_encryption_metadata(token: str) -> Dict[str, Any]:
    """Expose non-secret AES-GCM envelope details for the laboratory UI."""

    version, encoded, _signature = token.split(".", 2)
    if version not in {"CDNWM2", "CDNWM3"}:
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
        "aad": version,
        "nonce_base64url": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
        "ciphertext_base64url": base64.urlsafe_b64encode(ciphertext).decode("ascii").rstrip("="),
        "authentication_tag_base64url": base64.urlsafe_b64encode(tag).decode("ascii").rstrip("="),
    }

