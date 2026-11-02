from __future__ import annotations

import hashlib
import time

from services.watermark_service import WatermarkService
from utils.video import choose_video_example, encode_payload, extract_watermark_token, get_video_chunk, list_video_examples


class WatermarkDemoService:
    """Standalone forensic watermark demonstration independent of simulation state."""

    def __init__(self, watermark_service: WatermarkService) -> None:
        self._watermark_service = watermark_service

    def run(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        client_id = str(payload.get("client_id") or "demo-viewer")
        server_id = str(payload.get("server_id") or "demo-origin")
        chunk_number = int(payload.get("chunk", 0))
        requested_video_id = payload.get("video_id")
        if requested_video_id:
            video = next((item for item in list_video_examples() if item["video_id"] == str(requested_video_id)), {"video_id": str(requested_video_id), "label": str(requested_video_id), "content_type": "video/mp4"})
        else:
            video = choose_video_example(str(payload.get("exclude_video_id")) if payload.get("exclude_video_id") else None)
        original_bytes, content_type = get_video_chunk(chunk_number, video["video_id"])
        token, claim = self._watermark_service.issue(client_id, server_id, chunk_number)
        watermarked_bytes = token.encode("utf-8") + b"\n" + original_bytes
        extracted_token = extract_watermark_token(encode_payload(watermarked_bytes))
        verified_claim = self._watermark_service.verify(extracted_token)
        return {
            "demo": True,
            "content_type": content_type,
            "video_id": video["video_id"],
            "video_label": video["label"],
            "video_source": "scikit-video / dataset real",
            "video_asset_url": f"/api/security/watermark/demo/video?video_id={video['video_id']}",
            "chunk_number": chunk_number,
            "original_payload_base64": encode_payload(original_bytes),
            "watermarked_payload_base64": encode_payload(watermarked_bytes),
            "watermark_token": token,
            "noise_hex": claim.signature,
            "noise_source": "assinatura HMAC-SHA256 embutida no prefixo do chunk",
            "cryptographic_process": {
                "algorithm": "HMAC-SHA256",
                "key_material": "secret_key da CDN (nunca exposta ao cliente)",
                "signed_payload": "client_id + server_id + issued_at + chunk_id",
                "token_format": "CDNWM1.<payload-base64url>.<signature-hex>",
                "embedding": "token UTF-8 + byte \"\\n\" + chunk original",
                "transport_encoding": "Base64 apenas para transporte da demonstração",
                "verification": "decodificar, extrair claim, recalcular HMAC e comparar em tempo constante",
                "reversible_encryption": False,
            },
            "extracted_token": extracted_token,
            "claim": verified_claim.to_dict(),
            "round_trip_verified": verified_claim.signature == claim.signature,
            "payload_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "generated_at": time.time(),
        }

