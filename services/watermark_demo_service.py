from __future__ import annotations

import hashlib
import time

from services.watermark_service import WatermarkService
from utils.security import watermark_encryption_metadata
from utils.image_watermark import visual_marker
from utils.video_watermark import assess_video_robustness
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
        token, claim = self._watermark_service.issue(client_id, server_id, chunk_number, video["video_id"])
        generated_id = generate_visual_variants(video["video_id"], token, self._watermark_service.secret_key)
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
                "visual_transform": "localizador visual de 40 bits, sincronização de 16 bits, repetição 3x e portadora adaptativa de baixa frequência em grade 16×16; a terceira variante é apenas uma diferença amplificada em escala de cinza sobre preto",
            },
            "chunk_number": chunk_number,
            "original_payload_base64": encode_payload(original_bytes),
            "watermarked_payload_base64": encode_payload(watermarked_bytes),
            "watermark_token": token,
            "noise_hex": visual_marker(token),
            "noise_source": "digest SHA-256 do token convertido em 40 bits e embutido com sincronização, redundância, mascaramento perceptual e portadora pseudoaleatória",
            "key_fingerprint": key_fingerprint,
            "claim_before_encoding": claim.to_dict(),
            "encoded_claim": encoded_claim,
            "signature": signature,
            "payload_prefix": f"{token}\\n",
            "decryption_process": {
                **encryption_details,
                "steps": [
                    "extrair o envelope CDNWM3 do prefixo do chunk",
                    "validar a assinatura HMAC-SHA256 do envelope cifrado",
                    "descriptografar ciphertext com AES-256-GCM e AAD da versão do envelope",
                    "decodificar o JSON e validar client_id, server_id, issued_at, chunk_id e content_id",
                ],
                "decrypted_payload": verified_claim.to_dict(),
            },
            "robustness_checks": assess_video_robustness(original_asset, watermarked_asset, token, self._watermark_service.secret_key),
            "cryptographic_process": {
                "algorithm": "AES-256-GCM + HMAC-SHA256",
                "key_material": f"chave secreta da CDN · fingerprint SHA-256 {key_fingerprint} (valor nunca exposto)",
                "encryption_parameters": "AES-256-GCM · chave efetiva 256 bits · nonce aleatório 96 bits · tag 128 bits · AAD CDNWM3",
                "key_derivation": "SHA-256 com contexto CDN-Sentinel/watermark; a chave bruta não sai do backend",
                "signed_payload": "client_id + server_id + issued_at + chunk_id + content_id",
                "token_format": "CDNWM3.<nonce+ciphertext+tag-base64url>.<assinatura derivada por contexto>",
                "embedding": "token UTF-8 + byte '\\n' no transporte; sinal visual derivado de SHA-256 separado no MP4",
                "transport_encoding": "Base64 apenas para transporte da demonstração",
                "verification": "recalcular HMAC, descriptografar AES-GCM, validar tag e conferir o claim",
                "reversible_encryption": True,
                "robust_channel": "40 bits do digest visual, com sincronização de 16 bits e repetição 3x em 168 células de uma grade 16×16",
                "visual_parameters": "espalhamento em luminância com mascaramento adaptativo por textura, brilho e regiões uniformes; força controlada; detector sem imagem original",
                "robustness_limit": "a métrica é medida em amostras MP4 H.264 reais após blur, ruído, resize e re-encode; não substitui cobertura de ataques fora da matriz de testes",
            },
            "extracted_token": extracted_token,
            "claim": verified_claim.to_dict(),
            "round_trip_verified": verified_claim.signature == claim.signature,
            "payload_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "generated_at": time.time(),
        }
