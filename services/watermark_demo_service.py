from __future__ import annotations

import hashlib
import time

from services.watermark_service import WatermarkService
from utils.security import watermark_encryption_metadata
from utils.robust_watermark import assess_video_robustness
from utils.video import (
    choose_video_example,
    encode_payload,
    extract_watermark_token,
    generate_visual_variants,
    get_video_asset,
    get_video_chunk,
    list_video_examples,
)


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
            video = next(
                (
                    item
                    for item in list_video_examples()
                    if item["video_id"] == str(requested_video_id)
                    and not item["video_id"].endswith(("_watermarked", "_difference"))
                ),
                None,
            )
            if video is None:
                raise ValueError(f"vídeo local inválido: {requested_video_id}")
        else:
            video = choose_video_example(
                str(payload.get("exclude_video_id")) if payload.get("exclude_video_id") else None
            )

        original_bytes, content_type = get_video_chunk(chunk_number, video["video_id"])
        original_asset, _ = get_video_asset(video["video_id"], "original")
        token, claim = self._watermark_service.issue(client_id, server_id, chunk_number)
        generated_id = generate_visual_variants(video["video_id"], token)
        watermarked_asset, _ = get_video_asset(video["video_id"], "watermarked", generated_id)
        difference_asset, _ = get_video_asset(video["video_id"], "difference", generated_id)
        watermarked_bytes = token.encode("utf-8") + b"\n" + original_bytes
        extracted_token = extract_watermark_token(encode_payload(watermarked_bytes))
        verified_claim = self._watermark_service.verify(extracted_token)
        encoded_claim = token.split(".", 2)[1]
        signature = token.rsplit(".", 1)[1]
        encryption_details = watermark_encryption_metadata(token)
        key_fingerprint = hashlib.sha256(self._watermark_service.secret_key.encode("utf-8")).hexdigest()[:12]
        return {
            "demo": True,
            "content_type": content_type,
            "video_id": video["video_id"],
            "video_label": video["label"],
            "video_source": video.get("source", "asset MP4 local"),
            "video_asset_url": f"/api/security/watermark/demo/video?video_id={video['video_id']}&variant=original",
            "video_variants": {
                "original": f"/api/security/watermark/demo/video?video_id={video['video_id']}&variant=original",
                "watermarked": f"/api/security/watermark/demo/video?video_id={video['video_id']}&variant=watermarked&generated_id={generated_id}",
                "difference": f"/api/security/watermark/demo/video?video_id={video['video_id']}&variant=difference&generated_id={generated_id}",
            },
            "video_metadata": {
                "mime": content_type,
                "resolution": video.get("resolution", "1280x720"),
                "size_bytes": original_asset.stat().st_size,
                "source": video.get("source", "asset MP4 local"),
                "visual_transform": "sinal HMAC de 64 bits aplicado em 8×8 regiões de luminância; a terceira variante é diferença amplificada em escala de cinza sobre preto",
            },
            "chunk_number": chunk_number,
            "original_payload_base64": encode_payload(original_bytes),
            "watermarked_payload_base64": encode_payload(watermarked_bytes),
            "watermark_token": token,
            "noise_hex": claim.signature,
            "noise_source": "digest HMAC-SHA256 convertido em 64 bits e embutido como sinal de luminância no MP4 real",
            "key_fingerprint": key_fingerprint,
            "claim_before_encoding": claim.to_dict(),
            "encoded_claim": encoded_claim,
            "signature": signature,
            "payload_prefix": f"{token}\\n",
            "decryption_process": {
                **encryption_details,
                "steps": [
                    "extrair o envelope CDNWM2 do prefixo do chunk",
                    "validar a assinatura HMAC-SHA256 do envelope cifrado",
                    "descriptografar ciphertext com AES-256-GCM e AAD CDNWM2",
                    "decodificar o JSON e validar client_id, server_id, issued_at e chunk_id",
                ],
                "decrypted_payload": verified_claim.to_dict(),
            },
            "robustness_checks": assess_video_robustness(original_asset, watermarked_asset, token),
            "cryptographic_process": {
                "algorithm": "AES-256-GCM + HMAC-SHA256",
                "key_material": f"chave secreta da CDN · fingerprint SHA-256 {key_fingerprint} (valor nunca exposto)",
                "encryption_parameters": "AES-256-GCM · chave efetiva 256 bits · nonce aleatório 96 bits · tag 128 bits · AAD CDNWM2",
                "key_derivation": "SHA-256 com contexto CDN-Sentinel/watermark; a chave bruta não sai do backend",
                "signed_payload": "client_id + server_id + issued_at + chunk_id",
                "token_format": "CDNWM2.<nonce+ciphertext+tag-base64url>.<signature-hex>",
                "embedding": "token UTF-8 + byte '\\n' no transporte; sinal visual HMAC separado no MP4",
                "transport_encoding": "Base64 apenas para transporte da demonstração",
                "verification": "recalcular HMAC, descriptografar AES-GCM, validar tag e conferir o claim",
                "reversible_encryption": True,
                "robust_channel": "64 bits do digest HMAC distribuídos em 8×8 regiões de luminância dos frames H.264",
                "visual_parameters": "8×8 blocos · luminância · alpha 0,015 · diferença em grayscale com ganho 10x",
                "robustness_limit": "a métrica é medida em amostras MP4 H.264 reais de 1s após blur, ruído, resize e re-encode em intensidades variadas; não substitui um detector de produção",
            },
            "extracted_token": extracted_token,
            "claim": verified_claim.to_dict(),
            "round_trip_verified": verified_claim.signature == claim.signature,
            "payload_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "generated_at": time.time(),
        }
