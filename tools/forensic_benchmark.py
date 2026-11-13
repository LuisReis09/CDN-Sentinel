"""Reproducible local video watermark comparison and attack matrix.

Examples:
    python tools/forensic_benchmark.py --input data/media/bigbuckbunny.mp4 --seconds 3 --mode quick --output data/runtime/forensic-benchmark.json
    python tools/forensic_benchmark.py --dataset-root data/datasets/youtube_clipped_videos --mode full --seconds 10 --output data/runtime/dataset-benchmark.json

No neural results are generated unless a separate, actual model evaluation is
run.  Missing codecs are reported as unavailable rather than silently skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.watermark_registry import WatermarkRegistry
from services.watermark_service import WatermarkService
from tools.watermark_perceptual_experiments import _quality, _read_frames
from utils.image_watermark import SYNC_BITS, SYNC_MARKER, marker_bits, visual_marker
from watermark.ecc import Secded55Codec
from utils.video_watermark import detect_video, embed_video, transcode_video, probe_video_limits


def _command(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)


def _version(command: list[str]) -> str:
    try:
        return _command(command, timeout=15).stdout.strip().splitlines()[0]
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError):
        return "unavailable"


def _git_dirty() -> bool | None:
    try:
        return bool(_command(["git", "status", "--porcelain"], timeout=15).stdout.strip())
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _attacks(mode: str) -> list[tuple[str, str | None, str, int, str]]:
    attacks = [
        ("h264_crf23", None, "libx264", 23, "benign"),
        ("resize_75", "scale=iw*0.75:ih*0.75,scale=iw/0.75:ih/0.75", "libx264", 23, "benign"),
        ("blur_light", "boxblur=1:1", "libx264", 23, "moderate"),
    ]
    if mode == "quick":
        return attacks
    if mode == "refinement":
        return attacks + [
            ("h264_crf28", None, "libx264", 28, "moderate"),
            ("resize_50", "scale=iw*0.5:ih*0.5,scale=iw*2:ih*2", "libx264", 23, "moderate"),
            ("noise_light", "noise=alls=4:allf=u:all_seed=2026", "libx264", 23, "moderate"),
            ("grayscale", "format=gray", "libx264", 23, "moderate"),
            ("crop_moderate", "crop=iw*0.9:ih*0.9,scale=iw/0.9:ih/0.9", "libx264", 23, "moderate"),
            ("resize_blur_reencode", "scale=iw*0.75:ih*0.75,boxblur=1:1,scale=iw/0.75:ih/0.75", "libx264", 28, "severe"),
        ]
    attacks.extend((f"h264_crf{crf}", None, "libx264", crf, "benign" if crf <= 28 else "severe") for crf in (18, 28, 35, 40))
    attacks.extend((f"h265_crf{crf}", None, "libx265", crf, "moderate" if crf <= 28 else "severe") for crf in (23, 35))
    attacks.extend([
        ("av1_crf35", None, "libaom-av1", 35, "severe"),
        ("resize_50", "scale=iw*0.5:ih*0.5,scale=iw*2:ih*2", "libx264", 23, "moderate"),
        ("resize_25", "scale=iw*0.25:ih*0.25,scale=iw*4:ih*4", "libx264", 23, "severe"),
        ("blur_heavy", "boxblur=2:2", "libx264", 23, "severe"),
        ("noise_light", "noise=alls=4:allf=u:all_seed=2026", "libx264", 23, "moderate"),
        ("noise_heavy", "noise=alls=12:allf=u:all_seed=2026", "libx264", 23, "severe"),
        ("grayscale", "format=gray", "libx264", 23, "moderate"),
        ("brightness", "eq=brightness=0.06", "libx264", 23, "moderate"),
        ("contrast", "eq=contrast=1.2", "libx264", 23, "moderate"),
        ("letterbox", "pad=iw+40:ih+40:20:20:black", "libx264", 23, "moderate"),
        ("shift", "crop=iw-20:ih-20:20:20,pad=iw+20:ih+20:20:20:black", "libx264", 23, "moderate"),
        ("rotation", "rotate=0.03:ow=iw:oh=ih:fillcolor=black", "libx264", 23, "severe"),
        ("overlay", "drawbox=x=iw/4:y=ih/4:w=iw/2:h=40:color=white@0.7:t=fill", "libx264", 23, "moderate"),
        ("frame_drop", "select='not(mod(n,3))',setpts=N/FRAME_RATE/TB", "libx264", 23, "moderate"),
        ("temporal_trim", "trim=start=1,setpts=PTS-STARTPTS", "libx264", 23, "moderate"),
        ("fps_change", "fps=15", "libx264", 23, "moderate"),
        ("screen_record_sim", "scale=iw*0.75:ih*0.75,format=yuv420p,scale=iw/0.75:ih/0.75", "libx264", 35, "severe"),
        ("resize_reencode", "scale=iw*0.5:ih*0.5,scale=iw*2:ih*2", "libx264", 35, "severe"),
        ("crop_blur_reencode", "crop=iw*0.9:ih*0.9,scale=iw/0.9:ih/0.9,boxblur=1:1", "libx264", 35, "severe"),
    ])
    for pct in (5, 10, 25, 50):
        factor = math.sqrt(1 - pct / 100)
        attacks.append((f"crop_area_{pct}", f"crop=iw*{factor:.5f}:ih*{factor:.5f},scale=iw/{factor:.5f}:ih/{factor:.5f}", "libx264", 23, "moderate" if pct <= 10 else "severe"))
    return attacks


def _attack(source: Path, destination: Path, filter_expr: str | None, codec: str, crf: int) -> None:
    command = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-map", "0:v:0", "-an"]
    if filter_expr:
        command.extend(["-vf", filter_expr])
    command.extend(["-c:v", codec])
    if codec == "libaom-av1":
        command.extend(["-cpu-used", "8", "-row-mt", "1"])
    else:
        command.extend(["-preset", "ultrafast"])
    command.extend(["-crf", str(crf), "-pix_fmt", "yuv420p", str(destination)])
    _command(command, timeout=180)


def _detect(path: Path, secret: str, token: str, algorithm: str, step: float, *, qim3_soft_decode: bool = False) -> dict:
    started = time.perf_counter()
    evidence = detect_video(
        path, secret, algorithm=algorithm, dct_step=step, qim_step=step,
        qim3_soft_decode=qim3_soft_decode,
    )
    expected = visual_marker(token)
    recovered = evidence.get("marker")
    exact = evidence.get("status") == "CANDIDATE" and recovered == expected
    bits = sum(a == b for a, b in zip(marker_bits(str(recovered)), marker_bits(expected))) if recovered else None
    scores = evidence.get("scores")
    raw_errors = None
    raw_total = None
    if algorithm in {"qim2", "qim3"} and isinstance(scores, list):
        expected_bits = marker_bits(SYNC_MARKER, SYNC_BITS) + (
            Secded55Codec().encode(marker_bits(expected)) if algorithm == "qim3" else marker_bits(expected)
        )
        if len(scores) == len(expected_bits):
            raw_total = len(scores)
            raw_errors = sum(int((score < 0) != bool(bit)) for score, bit in zip(scores, expected_bits))
    return {
        "status": evidence.get("status"), "marker_exact": exact, "bits_correct_known_truth": bits,
        "bits_total": 48, "marker_ber_known_truth": round((48 - bits) / 48, 4) if bits is not None else None,
        "raw_channel_bit_errors_known_truth": raw_errors, "raw_channel_bits": raw_total,
        "raw_channel_ber_known_truth": round(raw_errors / raw_total, 4) if raw_total else None,
        "ecc_status": evidence.get("ecc_status"), "ecc_corrected_bits": evidence.get("ecc_corrected_bits", 0),
        "soft_decode": evidence.get("qim3_soft_decode") if algorithm == "qim3" else None,
        "confidence_uncalibrated": evidence.get("confidence"),
        "frames_sampled": evidence.get("frames_sampled"), "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _split(path: Path) -> str:
    bucket = int(hashlib.sha256(path.as_posix().encode()).hexdigest()[:8], 16) % 10
    return "development" if bucket < 6 else ("calibration" if bucket < 8 else "final")


def run(inputs: list[Path], *, mode: str = "quick", seconds: int = 3, algorithms: tuple[str, ...] = ("adaptive-spread", "dct", "qim2", "qim3"), artifact_root: Path | None = None, qim_step: float = 20.0, qim3_step: float = 28.0, qim3_soft_decode: bool = False, token_seed: str | None = None) -> dict:
    if not inputs:
        raise ValueError("nenhum vídeo disponível")
    report = {
        "schema_version": 4,
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "ffmpeg": _version(["ffmpeg", "-version"]),
            "git_commit": _version(["git", "rev-parse", "HEAD"]),
            "git_dirty": _git_dirty(),
        },
            "protocol": {"mode": mode, "clip_seconds": seconds, "algorithms": algorithms, "qim2_step": qim_step, "qim3_step": qim3_step, "qim3_soft_decode": qim3_soft_decode, "token_seed": token_seed, "control": "same H.264 CRF24 veryfast yuv420p", "human_review": "not performed"},
        "limitations": ["SSIM is windowed Gaussian 11x11 on luminance; MS-SSIM is still a three-scale approximation", "VMAF and LPIPS require separate optional tooling", "neural checkpoints are not evaluated by this script", "visual detector confidence is not statistically calibrated"],
        "videos": [],
    }
    with tempfile.TemporaryDirectory(prefix="cdn-forensic-benchmark-") as temporary:
        root = Path(temporary)
        service = WatermarkService("benchmark-forensic-secret-2026", WatermarkRegistry(root / "ledger.sqlite3"))
        for source in inputs:
            if not source.is_file():
                report["videos"].append({"source": str(source), "status": "UNAVAILABLE"})
                continue
            video_root = root / f"video-{len(report['videos'])}"
            video_root.mkdir()
            clip = video_root / "clip.mp4"
            _command(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-t", str(seconds), "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], timeout=180)
            control = video_root / "control.mp4"
            transcode_video(clip, control)
            reference_frames = _read_frames(control, max_frames=8)
            digest = hashlib.sha256()
            with source.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            token = (
                f"CDNWM4.benchmark.{token_seed}.{hashlib.sha256(source.as_posix().encode()).hexdigest()[:16]}"
                if token_seed else service.issue("benchmark-client", "benchmark-edge", len(report["videos"]), source.stem)[0]
            )
            entry = {"source": str(source), "sha256": digest.hexdigest(), "dataset_split": _split(source), "clip_probe": probe_video_limits(clip), "expected_marker": visual_marker(token), "algorithms": []}
            if artifact_root:
                target = artifact_root / f"video-{len(report['videos'])}"
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(clip, target / "source.mp4")
                shutil.copy2(control, target / "control.mp4")
            for algorithm in algorithms:
                step = {"adaptive-spread": 24.0, "dct": 10.0, "qim2": qim_step, "qim3": qim3_step}[algorithm]
                marked = video_root / f"{algorithm}.mp4"
                start = time.perf_counter()
                embed_video(clip, marked, token, service.secret_key, strength=step, algorithm=algorithm)
                if artifact_root:
                    shutil.copy2(marked, target / f"{algorithm}.mp4")
                embed_seconds = time.perf_counter() - start
                marked_frames = _read_frames(marked, max_frames=8)
                quality = _quality(reference_frames, marked_frames)
                quality["ssim_windowed"] = quality.pop("ssim")
                quality["ms_ssim_3scale_approx"] = quality.pop("ms_ssim")
                item = {
                    "algorithm": algorithm, "strength_or_step": step,
                    "quality_vs_control": quality,
                    "embed_seconds": round(embed_seconds, 3), "marked_size_bytes": marked.stat().st_size,
                    "clean_detection": _detect(marked, service.secret_key, token, algorithm, step, qim3_soft_decode=qim3_soft_decode),
                    "negative_detection": _detect(clip, service.secret_key, token, algorithm, step, qim3_soft_decode=qim3_soft_decode),
                    "attacks": [],
                }
                for name, filter_expr, codec, crf, severity in _attacks(mode):
                    attacked = video_root / f"{algorithm}-{name}.mkv"
                    try:
                        start = time.perf_counter()
                        _attack(marked, attacked, filter_expr, codec, crf)
                        if artifact_root and name in {"h264_crf23", "resize_75", "blur_light"}:
                            shutil.copy2(attacked, target / f"{algorithm}-{name}.mkv")
                        item["attacks"].append({"name": name, "severity": severity, "codec": codec, "crf": crf, "encode_seconds": round(time.perf_counter() - start, 3), **_detect(attacked, service.secret_key, token, algorithm, step, qim3_soft_decode=qim3_soft_decode)})
                    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError) as exc:
                        item["attacks"].append({"name": name, "severity": severity, "status": "UNAVAILABLE", "error": str(exc)[-300:]})
                entry["algorithms"].append(item)
            if artifact_root:
                artifact_hashes = {}
                for artifact in sorted(target.iterdir()):
                    if artifact.is_file():
                        artifact_hashes[artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
                (target / "sha256.json").write_text(json.dumps(artifact_hashes, indent=2), encoding="utf-8")
                entry["artifact_sha256"] = artifact_hashes
            report["videos"].append(entry)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--max-files", type=int, default=8)
    parser.add_argument("--mode", choices=("quick", "refinement", "full"), default="quick")
    parser.add_argument("--seconds", type=int, default=3)
    parser.add_argument("--algorithms", nargs="+", choices=("adaptive-spread", "dct", "qim2", "qim3"), default=["adaptive-spread", "dct", "qim2", "qim3"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--qim-step", type=float, default=20.0)
    parser.add_argument("--qim3-step", type=float, default=28.0)
    parser.add_argument("--qim3-soft-decode", action="store_true", help="enable the experimental confidence-aware SECDED decoder")
    parser.add_argument("--token-seed", help="deterministic visual-token seed for exact A/B detector comparisons")
    args = parser.parse_args()
    sources = list(args.input)
    if args.dataset_root:
        sources.extend(sorted(path for path in args.dataset_root.rglob("*") if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"})[:args.max_files])
    if not sources:
        sources = [Path("data/media/bigbuckbunny.mp4")]
    report = run(sources, mode=args.mode, seconds=args.seconds, algorithms=tuple(args.algorithms), artifact_root=args.artifact_dir, qim_step=args.qim_step, qim3_step=args.qim3_step, qim3_soft_decode=args.qim3_soft_decode, token_seed=args.token_seed)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
