from __future__ import annotations

import hashlib
import time

from services.watermark_service import WatermarkService
from utils.video import choose_video_example, encode_payload, extract_watermark_token, get_video_asset, get_video_chunk, list_video_examples
from utils.robust_watermark import assess_robustness


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
            video = next((item for item in list_video_examples() if item["video_id"] == str(requested_video_id) and not item["video_id"].endswith(("_watermarked", "_difference"))), None)
            if video is None:
                raise ValueError(f"vídeo local inválido: {requested_video_id}")
        else:
            video = choose_video_example(str(payload.get("exclude_video_id")) if payload.get("exclude_video_id") else None)
            if video["video_id"].endswith(("_watermarked", "_difference")):
                video = next(item for item in list_video_examples() if item["video_id"] == "cdn_sentinel_demo")
        original_bytes, content_type = get_video_chunk(chunk_number, video["video_id"])
        original_asset, _ = get_video_asset(video["video_id"])
        _, _ = get_video_asset(video["video_id"], "watermarked")
        _, _ = get_video_asset(video["video_id"], "difference")
        token, claim = self._watermark_service.issue(client_id, server_id, chunk_number)
        watermarked_bytes = token.encode("utf-8") + b"\n" + original_bytes
        extracted_token = extract_watermark_token(encode_payload(watermarked_bytes))
        verified_claim = self._watermark_service.verify(extracted_token)
        encoded_claim = token.split(".", 2)[1]
        signature = token.rsplit(".", 1)[1]
        key_fingerprint = hashlib.sha256(self._watermark_service.secret_key.encode("utf-8")).hexdigest()[:12]
        return {
            "demo": True,
            "content_type": content_type,
            "video_id": video["video_id"],
            "video_label": video["label"],
            "video_source": video.get("source", "scikit-video local opt-in"),
            "video_asset_url": f"/api/security/watermark/demo/video?video_id={video['video_id']}&variant=original",
            "video_variants": {
                "original": f"/api/security/watermark/demo/video?video_id={video['video_id']}&variant=original",
                "watermarked": f"/api/security/watermark/demo/video?video_id={video['video_id']}&variant=watermarked",
                "difference": f"/api/security/watermark/demo/video?video_id={video['video_id']}&variant=difference",
            },
            "video_metadata": {
                "mime": content_type,
                "resolution": video.get("resolution", "320x180"),
                "size_bytes": original_asset.stat().st_size,
                "source": "asset MP4 versionado; padrão testsrc2 próprio",
                "visual_transform": "drawbox + ajuste sutil de luminância; diferença = blend original/watermarked",
            },
            "chunk_number": chunk_number,
            "original_payload_base64": encode_payload(original_bytes),
            "watermarked_payload_base64": encode_payload(watermarked_bytes),
            "watermark_token": token,
            "noise_hex": claim.signature,
            "noise_source": "assinatura HMAC-SHA256 embutida no prefixo do chunk",
            "key_fingerprint": key_fingerprint,
            "claim_before_encoding": claim.to_dict(),
            "encoded_claim": encoded_claim,
            "signature": signature,
            "payload_prefix": f"{token}\\n",
            "robustness_checks": assess_robustness(original_bytes, token),
            "cryptographic_process": {
                "algorithm": "HMAC-SHA256",
                "key_material": f"chave secreta da CDN · fingerprint SHA-256 {key_fingerprint} (valor nunca exposto)",
                "signed_payload": "client_id + server_id + issued_at + chunk_id",
                "token_format": "CDNWM1.<payload-base64url>.<signature-hex>",
                "embedding": "token UTF-8 + byte \"\\n\" + chunk original",
                "transport_encoding": "Base64 apenas para transporte da demonstração",
                "verification": "decodificar, extrair claim, recalcular HMAC e comparar em tempo constante",
                "reversible_encryption": False,
                "robust_channel": "transformação visual real em frames H.264: luminância sutil e arquivo de diferença derivado",
                "robustness_limit": "esta versão demonstra pixels transformados; não afirma robustez contra re-encode. O detector spread-spectrum experimental permanece separado e não é aplicado ao MP4",
            },
            "extracted_token": extracted_token,
            "claim": verified_claim.to_dict(),
            "round_trip_verified": verified_claim.signature == claim.signature,
            "payload_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "generated_at": time.time(),
        }

