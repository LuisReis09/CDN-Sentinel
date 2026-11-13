"""Authenticated, versioned forensic claims.

CDNWM4 is intentionally independent from the legacy CDNWM1..3 envelope.  The
visual watermark carries only ``watermark_id``/fingerprint material; the
confidential claim is kept in the forensic ledger and is never sent in the
public media response.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


VERSION = "CDNWM4"
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


class ClaimError(ValueError):
    """Raised when a claim cannot be authenticated or validated."""


@dataclass(frozen=True)
class WatermarkClaim:
    version: str
    watermark_id: str
    session_id: str
    client_id: str
    server_id: str
    content_id: str
    issued_at: float
    valid_from: float
    valid_until: float
    algorithm_id: str
    key_id: str
    fingerprint_scheme: str
    segment_range: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WatermarkClaim":
        required = (
            "watermark_id", "session_id", "client_id", "server_id", "content_id",
            "issued_at", "valid_from", "valid_until", "algorithm_id", "key_id",
            "fingerprint_scheme", "segment_range",
        )
        if any(key not in value for key in required):
            raise ClaimError("claim CDNWM4 incompleto")
        for key in required:
            if key.endswith("_at") or key in {"valid_from", "valid_until"}:
                if not isinstance(value[key], (int, float)) or not math.isfinite(float(value[key])):
                    raise ClaimError(f"{key} inválido")
            elif not isinstance(value[key], str) or not value[key] or len(value[key]) > 240:
                raise ClaimError(f"{key} inválido")
        if any(not _ID_RE.fullmatch(str(value[key])) for key in ("watermark_id", "session_id", "client_id", "server_id", "key_id")) or "." in str(value["key_id"]):
            raise ClaimError("identificador do claim inválido")
        if not float(value["valid_from"]) <= float(value["issued_at"]) <= float(value["valid_until"]):
            raise ClaimError("janela de validade inválida")
        return cls(
            version=str(value.get("version", VERSION)),
            watermark_id=str(value["watermark_id"]), session_id=str(value["session_id"]),
            client_id=str(value["client_id"]), server_id=str(value["server_id"]),
            content_id=str(value["content_id"]), issued_at=float(value["issued_at"]),
            valid_from=float(value["valid_from"]), valid_until=float(value["valid_until"]),
            algorithm_id=str(value["algorithm_id"]), key_id=str(value["key_id"]),
            fingerprint_scheme=str(value["fingerprint_scheme"]), segment_range=str(value["segment_range"]),
        )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


def _key(secret: str, kid: str) -> bytes:
    if not isinstance(secret, str) or len(secret) < 16:
        raise ClaimError("segredo deve ter ao menos 16 caracteres; use material aleatório de alta entropia")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"CDN-Sentinel/{VERSION}/{kid}".encode()).derive(secret.encode())


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def create_claim_token(claim: WatermarkClaim | Mapping[str, Any], secret: str) -> str:
    normalized = claim if isinstance(claim, WatermarkClaim) else WatermarkClaim.from_mapping(claim)
    payload = normalized.to_dict()
    payload["version"] = VERSION
    kid = normalized.key_id
    nonce = os.urandom(12)
    encoded = _b64(nonce + AESGCM(_key(secret, kid)).encrypt(nonce, _canonical(payload), VERSION.encode()))
    mac = hmac.new(_key(secret, f"signing/{kid}"), f"{VERSION}.{kid}.{encoded}".encode("ascii"), hashlib.sha256).hexdigest()
    return f"{VERSION}.{kid}.{encoded}.{mac}"


def verify_claim_token(token: str, secret: str, *, now: float | None = None, allow_expired: bool = False) -> WatermarkClaim:
    try:
        version, kid, encoded, mac = token.split(".", 3)
        if version != VERSION or not _ID_RE.fullmatch(kid) or "." in kid:
            raise ClaimError("versão ou kid de claim inválidos")
        expected = hmac.new(_key(secret, f"signing/{kid}"), f"{VERSION}.{kid}.{encoded}".encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ClaimError("assinatura do claim inválida")
        envelope = _unb64(encoded)
        if len(envelope) <= 12 + 16:
            raise ClaimError("envelope do claim incompleto")
        nonce, ciphertext = envelope[:12], envelope[12:]
        payload = json.loads(AESGCM(_key(secret, kid)).decrypt(nonce, ciphertext, VERSION.encode()).decode("utf-8"))
        claim = WatermarkClaim.from_mapping(payload)
        if claim.key_id != kid:
            raise ClaimError("kid não corresponde ao claim")
        if not allow_expired:
            current = time.time() if now is None else float(now)
            if current < claim.valid_from or current > claim.valid_until:
                raise ClaimError("claim fora da janela de validade")
        return claim
    except ClaimError:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError, InvalidTag, IndexError) as exc:
        raise ClaimError(f"claim não pôde ser autenticado: {exc}") from exc


def claim_metadata(token: str) -> dict[str, Any]:
    """Return safe envelope metadata; never decrypts or exposes claim fields."""
    version, kid, encoded, _mac = token.split(".", 3)
    envelope = _unb64(encoded)
    return {"version": version, "key_id": kid, "algorithm": "AES-256-GCM + HMAC-SHA256", "nonce_bytes": 12, "ciphertext_bytes": max(0, len(envelope) - 12 - 16)}
