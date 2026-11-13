from __future__ import annotations

import base64
import hashlib
import time
import uuid

from services.forensic_investigation_service import ForensicInvestigationService
from services.watermark_service import WatermarkService
from tools.watermark_perceptual_experiments import _quality, _read_frames
from utils.image_watermark import visual_marker
from utils.security import watermark_encryption_metadata
from utils.video import (
    choose_video_example,
    encode_payload,
    generate_visual_variants,
    generate_forensic_variants,
    get_video_asset,
    get_video_asset_bytes,
    list_video_examples,
    video_frame_timestamps,
)
from utils.video_watermark import assess_video_robustness, probe_video_limits
from watermark.claims import claim_metadata, verify_claim_token


class WatermarkDemoService:
    """Standalone forensic watermark demonstration independent of simulation state."""

    def __init__(self, watermark_service: WatermarkService, investigator: ForensicInvestigationService | None = None) -> None:
        self._watermark_service = watermark_service
        self._investigator = investigator or ForensicInvestigationService(watermark_service)

    def run_forensic(self, payload: dict | None = None) -> dict:
        """Run the CDNWM4 issue, embed, ledger resolution and content gate."""
        payload = payload or {}
        algorithm = str(payload.get("algorithm") or "qim3")
        if algorithm not in {"qim2", "qim3"}:
            raise ValueError("algorithm deve ser qim2 ou qim3")
        videos = list_video_examples()
        dataset_videos = [item for item in videos if item.get("source") == "kishan51/youtube_clipped_videos"]
        requested_video_id = str(payload.get("video_id") or "")
        if dataset_videos:
            video = next((item for item in dataset_videos if item["video_id"] == requested_video_id), dataset_videos[0])
        else:
            video = next((item for item in videos if item["video_id"] == (requested_video_id or "bigbuckbunny")), None)
        if video is None:
            raise ValueError("video_id local invalido")
        video_id = video["video_id"]
        source, _ = get_video_asset(video_id)
        limits = probe_video_limits(source)
        if limits["duration_seconds"] < 3:
            raise ValueError("o Studio forense requer um clipe de pelo menos 3 s")
        if limits["width"] > 1920 or limits["height"] > 1080 or limits["fps"] > 60:
            raise ValueError("o clipe excede o limite do Studio (1080p, 60 fps)")
        algorithm_id = "dct-qim-v3" if algorithm == "qim3" else "dct-qim-v2"
        token, claim = self._watermark_service.issue_forensic_claim(
            client_id=str(payload.get("client_id") or "studio-viewer")[:80],
            server_id="studio-origin", content_id=video_id,
            session_id=uuid.uuid4().hex, segment_range="0-4s", algorithm_id=algorithm_id,
        )
        generated_id = generate_forensic_variants(video_id, token, self._watermark_service.secret_key, algorithm)
        marked, _ = get_video_asset(video_id, "watermarked", generated_id)
        control, _ = get_video_asset(video_id, "control", generated_id)
        original, _ = get_video_asset(video_id, "original", generated_id)
        residual, _ = get_video_asset(video_id, "residual", generated_id)
        difference, _ = get_video_asset(video_id, "difference", generated_id)
        verified_claim = verify_claim_token(token, self._watermark_service.secret_key, allow_expired=True)
        token_version, token_key_id, encoded_envelope, token_mac = token.split(".", 3)
        envelope = base64.urlsafe_b64decode(encoded_envelope + "=" * (-len(encoded_envelope) % 4))
        original_bytes = original.read_bytes()
        marked_bytes = marked.read_bytes()
        investigation = self._investigator.investigate_video(marked, source="studio-local-demonstration", algorithm=algorithm)
        detection = investigation.get("evidence", {})
        quality = _quality(_read_frames(control, max_frames=8), _read_frames(marked, max_frames=8))
        quality["ssim_windowed"] = quality.pop("ssim")
        quality["ms_ssim_3scale_approx"] = quality.pop("ms_ssim")
        robustness = assess_video_robustness(original, marked, token, self._watermark_service.secret_key,
                                             algorithm=algorithm)
        paths = {"original": original, "control": control, "marked": marked, "residual": residual, "difference": difference}
        probes = {name: probe_video_limits(path) for name, path in paths.items()}
        timestamps = {name: video_frame_timestamps(path) for name, path in paths.items()}
        frame_count = len(timestamps["original"])
        maximum_timestamp_drift = max(
            (abs(left - right) for values in timestamps.values() for left, right in zip(timestamps["original"], values)),
            default=0.0,
        )
        aligned = (
            all(probe["width"] == probes["original"]["width"] and probe["height"] == probes["original"]["height"]
                and abs(probe["fps"] - probes["original"]["fps"]) < 0.02
                and abs(probe["duration_seconds"] - probes["original"]["duration_seconds"]) < 0.12
                for probe in probes.values())
            and frame_count > 0 and all(len(values) == frame_count for values in timestamps.values())
            and maximum_timestamp_drift < 0.25 / probes["original"]["fps"]
        )
        variants = {
            variant: f"/api/security/watermark/demo/video?video_id={video_id}&variant={variant}&generated_id={generated_id}"
            for variant in ("original", "control", "watermarked", "residual", "difference", "detection_map")
        }
        return {
            "demo": True, "pipeline": "CDNWM4", "algorithm": algorithm,
            "algorithm_id": algorithm_id, "fingerprint_scheme": claim.fingerprint_scheme,
            "video_id": video_id, "video_label": video["label"], "source": video.get("source"),
            "claim": claim.to_dict(), "issued_marker": visual_marker(token),
            "visual_detection": detection, "ledger_status": detection.get("forensic_status"),
            "investigation": {key: value for key, value in investigation.items() if key != "evidence"},
            "quality_vs_control": quality, "video_variants": variants,
            "robustness_checks": robustness,
            "forensic_envelope": {
                "format": "CDNWM4.<key_id>.<nonce+ciphertext+tag base64url>.<HMAC-SHA256 hex>",
                "token": token,
                "version": token_version,
                "key_id": token_key_id,
                "algorithm": "AES-256-GCM + HMAC-SHA256 (HKDF-SHA256)",
                "algorithm_key": self._watermark_service.secret_key,
                "nonce_base64url": base64.urlsafe_b64encode(envelope[:12]).decode("ascii").rstrip("="),
                "ciphertext_and_tag_base64url": base64.urlsafe_b64encode(envelope[12:]).decode("ascii").rstrip("="),
                "hmac_sha256": token_mac,
                "metadata": claim_metadata(token),
                "claim_before_encryption": claim.to_dict(),
                "claim_after_decryption": verified_claim.to_dict(),
            },
            "media_payloads": {
                "original": {
                    "sha256": hashlib.sha256(original_bytes).hexdigest(),
                    "size_bytes": len(original_bytes),
                    "prefix_base64": base64.b64encode(original_bytes[:48]).decode("ascii"),
                },
                "watermarked": {
                    "sha256": hashlib.sha256(marked_bytes).hexdigest(),
                    "size_bytes": len(marked_bytes),
                    "prefix_base64": base64.b64encode(marked_bytes[:48]).decode("ascii"),
                },
                "note": "Os prefixes representam apenas o cabeçalho MP4. O ruído é inserido nos coeficientes DCT dos frames, não como texto anexado ao arquivo.",
            },
            "video_alignment": {"aligned": aligned, "probes": probes,
                                "frame_count": frame_count, "max_timestamp_drift_ms": round(maximum_timestamp_drift * 1000, 3)},
            "diagnostics": {
                "residual": "absolute pixel difference before video encode, grayscale, display gain 8x",
                "difference": "per-channel absolute RGB difference of separately encoded control and marked video, display gain 8x",
                "detection_map": "first marked frame; coefficient correlation against issued marker, green agrees, red disagrees, gray masked; claim-conditioned diagnostic, not blind detector result",
            },
            "generated_at": time.time(),
        }

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
