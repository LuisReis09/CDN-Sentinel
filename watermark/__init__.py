"""Versioned forensic watermarking contracts.

The package deliberately keeps the visual channel and the forensic claim
separate.  Visual extraction produces an untrusted marker; only the ledger
and authenticated claim can turn it into an attribution.
"""

from watermark.claims import ClaimError, WatermarkClaim, create_claim_token, verify_claim_token

__all__ = ["ClaimError", "WatermarkClaim", "create_claim_token", "verify_claim_token"]
