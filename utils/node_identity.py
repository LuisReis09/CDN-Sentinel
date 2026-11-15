"""Asymmetric identities for CDN node-to-node envelopes.

The control plane still encrypts local simulation traffic with AES-GCM.  This
module adds an Ed25519 identity to each CDN node so a receiving peer can prove
which node signed a gossip package without sharing the sender's private key.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def generate_node_identity() -> tuple[str, str]:
    """Return URL-safe raw Ed25519 private/public key material."""

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return _encode(private_bytes), _encode(public_bytes)


def public_key_from_private(private_key: str) -> str:
    key = Ed25519PrivateKey.from_private_bytes(_decode(private_key))
    return _encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def _message(sender_id: str, path: str, encrypted_payload: Any) -> bytes:
    if not sender_id or not path:
        raise ValueError("identidade ou caminho de mensagem ausente")
    return json.dumps(
        {"sender_id": sender_id, "path": path, "encrypted_payload": encrypted_payload},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_peer_envelope(private_key: str, sender_id: str, path: str, encrypted_payload: Any) -> str:
    key = Ed25519PrivateKey.from_private_bytes(_decode(private_key))
    return _encode(key.sign(_message(sender_id, path, encrypted_payload)))


def verify_peer_envelope(public_key: str, sender_id: str, path: str, encrypted_payload: Any, signature: str) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(_decode(public_key))
        key.verify(_decode(signature), _message(sender_id, path, encrypted_payload))
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False
