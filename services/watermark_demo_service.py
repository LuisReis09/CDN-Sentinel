from __future__ import annotations

import hashlib
import time

from services.watermark_service import WatermarkService
from utils.image_watermark import visual_marker
from utils.security import watermark_encryption_metadata
from utils.video import (
    choose_video_example,
    encode_payload,
    generate_visual_variants,
    get_video_asset,
    get_video_asset_bytes,
    list_video_examples,
)
from utils.video_watermark import assess_video_robustness, probe_video_limits


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

        original_bytes, content_type = get_video_asset_bytes(video["video_id"])
        original_asset, _ = get_video_asset(video["video_id"], "original")
        token, claim = self._watermark_service.issue(client_id, server_id, chunk_number, video["video_id"])
        generated_id = generate_visual_variants(video["video_id"], token, self._watermark_service.secret_key)
        watermarked_asset, _ = get_video_asset(video["video_id"], "watermarked", generated_id)
        difference_asset, _ = get_video_asset(video["video_id"], "difference", generated_id)
        watermarked_bytes = watermarked_asset.read_bytes()
        visual_detection = self._watermark_service.detect_video(watermarked_asset)
        verified_claim = self._watermark_service.verify(token)
        encoded_claim = token.split(".", 2)[1]
        signature = token.rsplit(".", 1)[1]
        encryption_details = watermark_encryption_metadata(token)
        key_fingerprint = hashlib.sha256(self._watermark_service.secret_key.encode("utf-8")).hexdigest()[:12]
        preview_size = 96
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
                "fps": probe_video_limits(original_asset)["fps"],
                "source": video.get("source", "asset MP4 local"),
                "visual_transform": "marcador visual autenticado de 48 bits, SECDED Hamming(13,8), sincronização redundante e portadora adaptativa em grade 16×16; a terceira variante é apenas uma diferença amplificada para diagnóstico",
            },
            "chunk_number": chunk_number,
            "original_payload_base64": encode_payload(original_bytes[:preview_size]),
            "watermarked_payload_base64": encode_payload(watermarked_bytes[:preview_size]),
            "payload_is_preview": True,
            "watermark_token": token,
            "noise_hex": visual_marker(token),
            "noise_source": "digest SHA-256 do token convertido em 48 bits e embutido no vídeo; não é um prefixo do MP4",
            "key_fingerprint": key_fingerprint,
            "claim_before_encoding": claim.to_dict(),
            "encoded_claim": encoded_claim,
            "signature": signature,
            "payload_prefix": "não existe prefixo textual no MP4 entregue; o token é metadado auxiliar separado",
            "decryption_process": {
                **encryption_details,
                "steps": [
                    "receber o token auxiliar ou o marcador visual recuperado do vídeo",
                    "validar a assinatura HMAC-SHA256 do envelope cifrado",
                    "descriptografar ciphertext com AES-256-GCM e AAD da versão do envelope",
                    "decodificar o JSON e validar client_id, server_id, issued_at, chunk_id e content_id",
                ],
                "decrypted_payload": verified_claim.to_dict(),
            },
            "robustness_checks": assess_video_robustness(original_asset, watermarked_asset, token, self._watermark_service.secret_key),
            "visual_detection": visual_detection,
            "verification": {
                "transport_token": "VALID" if verified_claim.signature == claim.signature else "INVALID",
                "visual_embedded": True,
                "visual_detection": visual_detection.get("status"),
                "visual_authentication": visual_detection.get("authentication"),
                "forensic_status": "VALID" if visual_detection.get("status") == "VALID" else "RESTRICTED",
            },
            "cryptographic_process": {
                "algorithm": "AES-256-GCM + HMAC-SHA256",
                "key_material": f"chave secreta da CDN · fingerprint SHA-256 {key_fingerprint} (valor nunca exposto)",
                "encryption_parameters": "AES-256-GCM · chave efetiva 256 bits · nonce aleatório 96 bits · tag 128 bits · AAD CDNWM3",
                "key_derivation": "SHA-256 com contexto CDN-Sentinel/watermark; a chave bruta não sai do backend",
                "signed_payload": "client_id + server_id + issued_at + chunk_id + content_id",
                "token_format": "CDNWM3.<nonce+ciphertext+tag-base64url>.<assinatura derivada por contexto>",
                "embedding": "marcador derivado de SHA-256 e inserido visualmente nos frames; nenhum token é concatenado ao MP4",
                "transport_encoding": "Base64 apenas para o preview JSON legado; a entrega de mídia usa bytes MP4",
                "verification": "recalcular HMAC, descriptografar AES-GCM, validar tag e conferir o claim; depois autenticar o marcador visual exatamente no registro",
                "reversible_encryption": True,
                "robust_channel": "48 bits de digest visual, sincronização de 8 bits, SECDED Hamming(13,8), repetição 3x e 250 slots na grade 16×16",
                "visual_parameters": "espalhamento de luminância com mascaramento adaptativo por textura, brilho e regiões uniformes; detector sem imagem original",
                "robustness_limit": "a taxa de recuperação é medida nas transformações do relatório e não substitui a cobertura de ataques fora da matriz de testes",
            },
            "extracted_token": token,
            "claim": verified_claim.to_dict(),
            "round_trip_verified": verified_claim.signature == claim.signature,
            "payload_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "watermarked_payload_sha256": hashlib.sha256(watermarked_bytes).hexdigest(),
            "generated_at": time.time(),
        }
