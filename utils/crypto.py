"""Small AES-256-GCM helpers shared by internal messages and watermark claims."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def derive_key(secret: str, context: str) -> bytes:
    """Derive an independent 256-bit key for each protocol context."""

    return hashlib.sha256(f"CDN-Sentinel/{context}\x00{secret}".encode("utf-8")).digest()


def encrypt_bytes(plaintext: bytes, secret: str, *, aad: str = "", context: str = "internal") -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(derive_key(secret, context)).encrypt(nonce, plaintext, aad.encode("utf-8"))
    return nonce, ciphertext


def decrypt_bytes(nonce: bytes, ciphertext: bytes, secret: str, *, aad: str = "", context: str = "internal") -> bytes:
    return AESGCM(derive_key(secret, context)).decrypt(nonce, ciphertext, aad.encode("utf-8"))


def encrypt_payload(payload: Any, secret: str, *, aad: str = "") -> dict[str, Any]:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    nonce, ciphertext = encrypt_bytes(raw, secret, aad=aad, context="internal")
    return {
        "_encrypted": True,
        "version": "CDNENC1",
        "algorithm": "AES-256-GCM",
        "nonce": _b64url_encode(nonce),
        "ciphertext": _b64url_encode(ciphertext),
    }


def is_encrypted_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("_encrypted") is True and payload.get("version") == "CDNENC1"


def decrypt_payload(payload: dict[str, Any], secret: str, *, aad: str = "") -> Any:
    if not is_encrypted_payload(payload):
        raise ValueError("payload interno não está cifrado")
    try:
        nonce = _b64url_decode(str(payload["nonce"]))
        ciphertext = _b64url_decode(str(payload["ciphertext"]))
        raw = decrypt_bytes(nonce, ciphertext, secret, aad=aad, context="internal")
        return json.loads(raw.decode("utf-8"))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, InvalidTag) as exc:
        raise ValueError("payload interno não pôde ser autenticado/descriptografado") from exc


def encrypted_payload_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Return safe display metadata without exposing keys or plaintext."""

    nonce = _b64url_decode(str(payload.get("nonce", "")))
    ciphertext = _b64url_decode(str(payload.get("ciphertext", "")))
    return {
        "version": payload.get("version"),
        "algorithm": payload.get("algorithm", "AES-256-GCM"),
        "nonce_base64url": _b64url_encode(nonce),
        "ciphertext_bytes": max(0, len(ciphertext) - 16),
        "auth_tag_bytes": 16,
    }
