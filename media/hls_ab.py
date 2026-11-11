"""Local HLS A/B preparation with two cached physical segment variants.

Preparation transcodes each master once into aligned temporal segments, then
embeds both A and B in each segment.  Session creation selects cached variants
and writes only a playlist plus a ledger entry; it never encodes media.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from services.content_provider import ContentProvider, HybridContentProvider
from services.watermark_registry import WatermarkRegistry
from services.watermark_service import WatermarkService
from utils.video_watermark import embed_video, probe_video_limits
from utils.video_watermark import detect_video
from utils.image_watermark import visual_marker


class HLSABService:
    def __init__(
        self,
        watermark_service: WatermarkService,
        provider: ContentProvider | None = None,
        *,
        cache_root: str | Path | None = None,
        segment_seconds: int = 2,
    ) -> None:
        if segment_seconds < 1 or segment_seconds > 10:
            raise ValueError("segment_seconds deve estar entre 1 e 10")
        self.watermark_service = watermark_service
        self.provider = provider or HybridContentProvider()
        self.registry: WatermarkRegistry = watermark_service._registry_store
        self.cache_root = Path(cache_root or os.getenv("CDN_HLS_CACHE_ROOT", "data/runtime/hls-ab")).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.segment_seconds = segment_seconds
        self._lock = threading.RLock()

    def _source(self, content_id: str) -> Path:
        source, content_type = self.provider.resolve_asset(content_id, 0)
        if not content_type.startswith("video/") or not source.is_file():
            raise FileNotFoundError("conteúdo de vídeo não disponível")
        return source.resolve()

    def _cache_id(self, source: Path, content_id: str) -> str:
        stat = source.stat()
        raw = f"CDNHLSAB1|{source}|{stat.st_mtime_ns}|{stat.st_size}|{content_id}|{self.segment_seconds}|{hashlib.sha256(self.watermark_service.secret_key.encode()).hexdigest()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def prepare(self, content_id: str) -> dict:
        source = self._source(content_id)
        cache_id = self._cache_id(source, content_id)
        root = self.cache_root / cache_id
        with self._lock:
            if (root / "READY").is_file():
                count = len(list((root / "A").glob("*.ts")))
                if count and count == len(list((root / "B").glob("*.ts"))):
                    return {"cache_id": cache_id, "segments": count, "root": root, "cache_hit": True}
            with tempfile.TemporaryDirectory(prefix="hls-prepare-", dir=self.cache_root) as temporary:
                staged = Path(temporary)
                (staged / "source").mkdir()
                (staged / "A").mkdir()
                (staged / "B").mkdir()
                limits = probe_video_limits(source)
                if limits["duration_seconds"] > 180 or limits["width"] * limits["height"] > 3840 * 2160:
                    raise ValueError("conteúdo excede limites locais de preparação")
                fps = float(limits["fps"])
                gop = max(1, round(fps * self.segment_seconds))
                command = [
                    "ffmpeg", "-y", "-v", "error", "-i", str(source),
                    "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                    "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
                    "-force_key_frames", f"expr:gte(t,n_forced*{self.segment_seconds})",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-f", "segment",
                    "-segment_time", str(self.segment_seconds), "-reset_timestamps", "1",
                    str(staged / "source" / "%04d.mp4"),
                ]
                subprocess.run(command, check=True, capture_output=True, timeout=180)
                sources = sorted((staged / "source").glob("*.mp4"))
                if not sources:
                    raise RuntimeError("segmentação não produziu arquivos")
                durations = []
                for index, segment in enumerate(sources):
                    probe = subprocess.run([
                        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(segment),
                    ], check=True, capture_output=True, text=True, timeout=30)
                    durations.append(float(probe.stdout.strip()))
                    for variant in ("A", "B"):
                        token = f"CDNAB1|{content_id}|{index}|{variant}"
                        marked = staged / variant / f"{index:04d}.mp4"
                        embed_video(segment, marked, token, self.watermark_service.secret_key)
                        transport = staged / variant / f"{index:04d}.ts"
                        subprocess.run([
                            "ffmpeg", "-y", "-v", "error", "-i", str(marked), "-map", "0:v:0", "-map", "0:a?",
                            "-c", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "mpegts", str(transport),
                        ], check=True, capture_output=True, timeout=60)
                        marked.unlink()
                (staged / "durations.json").write_text(json.dumps(durations), encoding="utf-8")
                (staged / "READY").write_text(str(len(sources)), encoding="ascii")
                if root.exists():
                    raise RuntimeError("cache HLS parcial já existe; requer inspeção local")
                staged.rename(root)
            return {"cache_id": cache_id, "segments": len(sources), "root": root, "cache_hit": False}

    def create_session(self, client_id: str, server_id: str, content_id: str, *, viewer_session_id: str | None = None) -> dict:
        prepared = self.prepare(content_id)
        count = prepared["segments"]
        with self._lock:
            if viewer_session_id:
                existing = self.registry.ab_session(self.watermark_service.secret_key, viewer_session_id)
                if existing:
                    if existing["client_id"] != client_id or existing["content_id"] != content_id:
                        raise PermissionError("sessão de espectador pertence a outra entrega")
                    return {
                        "session_id": viewer_session_id, "content_id": content_id,
                        "segments": len(existing["fingerprint"]), "cache_hit": True,
                        "fingerprint_bits": len(existing["fingerprint"]),
                        "attribution_ready": False,
                        "manifest_url": f"/api/clients/{client_id}/hls/{viewer_session_id}/index.m3u8",
                        "algorithm_id": "hls-ab-v1",
                    }
            for _ in range(32):
                session_id = viewer_session_id or f"hls-{uuid.uuid4().hex}"
                pattern = "".join(
                    "B" if hmac.digest(self.watermark_service.secret_key.encode(), f"{session_id}|{content_id}|{index}".encode(), "sha256")[0] & 1 else "A"
                    for index in range(count)
                )
                if not self.registry.ab_pattern_exists(content_id, pattern):
                    break
            else:
                raise RuntimeError("espaço de fingerprints A/B esgotado para este conteúdo")
            token, claim = self.watermark_service.issue_forensic_claim(
                client_id=client_id, server_id=server_id, content_id=content_id,
                session_id=session_id, segment_range=f"0-{count-1}", algorithm_id="hls-ab-v1",
                fingerprint_scheme="ab-segment-sequence",
            )
            self.registry.put_ab_session(self.watermark_service.secret_key, session_id, client_id, content_id, claim.watermark_id, prepared["cache_id"], pattern)
        return {
            "session_id": session_id, "content_id": content_id, "segments": count,
            "cache_hit": prepared["cache_hit"], "fingerprint_bits": count,
            "attribution_ready": False,
            "manifest_url": f"/api/clients/{client_id}/hls/{session_id}/index.m3u8",
            "algorithm_id": "hls-ab-v1",
        }

    def manifest(self, session_id: str, client_id: str) -> str:
        session = self.registry.ab_session(self.watermark_service.secret_key, session_id)
        if session is None or session["client_id"] != client_id:
            raise KeyError("sessão HLS não encontrada")
        durations = json.loads((self.cache_root / session["cache_id"] / "durations.json").read_text(encoding="utf-8"))
        target = max(1, math.ceil(max(durations)))
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{target}", "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD"]
        for index in range(len(session["fingerprint"])):
            if index:
                lines.append("#EXT-X-DISCONTINUITY")
            lines.extend([f"#EXTINF:{durations[index]:.3f},", f"{index:04d}.ts"])
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"

    def segment(self, session_id: str, client_id: str, index: int) -> Path:
        session = self.registry.ab_session(self.watermark_service.secret_key, session_id)
        if session is None or session["client_id"] != client_id:
            raise KeyError("sessão HLS não encontrada")
        if index < 0 or index >= len(session["fingerprint"]):
            raise IndexError("segmento inexistente")
        path = self.cache_root / session["cache_id"] / session["fingerprint"][index] / f"{index:04d}.ts"
        if not path.is_file():
            raise FileNotFoundError("segmento não disponível")
        return path

    def detect_segment_variant(self, path: Path, content_id: str, index: int) -> dict:
        evidence = detect_video(path, self.watermark_service.secret_key)
        if evidence.get("status") != "CANDIDATE":
            return {"status": "INCONCLUSIVE", "index": index, "detector_status": evidence.get("status")}
        for variant in ("A", "B"):
            expected = visual_marker(f"CDNAB1|{content_id}|{index}|{variant}")
            if evidence.get("marker") == expected:
                return {"status": "RECOVERED", "index": index, "variant": variant, "marker": expected, "frames_sampled": evidence.get("frames_sampled")}
        return {"status": "INCONCLUSIVE", "index": index, "reason": "marcador não corresponde a A ou B"}

    def analyze_segments(self, content_id: str, segments: list[Path]) -> dict:
        decisions = [self.detect_segment_variant(path, content_id, index) for index, path in enumerate(segments)]
        if any(item["status"] != "RECOVERED" for item in decisions):
            return {"status": "INCONCLUSIVE", "segments": decisions, "reason": "sequência parcial ou ilegível"}
        pattern = "".join(item["variant"] for item in decisions)
        if len(pattern) < 32:
            return {"status": "INCONCLUSIVE", "fingerprint": pattern, "segments": decisions, "reason": "menos de 32 escolhas A/B; entropia insuficiente para atribuição"}
        # A complete 32+ segment sequence still requires independent media
        # matching and statistical calibration before attribution.  Expose an
        # exact candidate only; never trigger sanctions from this pathway.
        return {"status": "CANDIDATE", "fingerprint": pattern, "segments": decisions, "attribution": "NONE"}
