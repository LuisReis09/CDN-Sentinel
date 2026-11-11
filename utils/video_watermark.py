"""Streaming video adapter for the independent image watermark detector."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from utils.image_watermark import (
    ImageWatermarkUnsupported,
    _decode_score_vector,
    _decode_scores,
    classify_image_evidence,
    detect_image,
    embed_image,
    marker_bits,
    visual_marker,
)


VIDEO_STRENGTH = 16.0


def _probe(path: Path) -> tuple[int, int, float]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "csv=p=0:s=,", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height, rate = result.stdout.strip().split(",", 2)
    numerator, denominator = rate.split("/", 1)
    return int(width), int(height), float(numerator) / float(denominator)


def _frame_command(path: Path, width: int, height: int, fps: float) -> list[str]:
    return [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-r", f"{fps:.6f}", "-",
    ]


def embed_video(source: Path, destination: Path, token: str, secret: str, strength: float = VIDEO_STRENGTH) -> dict:
    """Watermark a video frame-by-frame with bounded memory usage."""
    width, height, fps = _probe(source)
    frame_size = width * height * 3
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cdn-watermark-") as temporary:
        silent = Path(temporary) / "video.mp4"
        encoder = subprocess.Popen(
            [
                "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{width}x{height}", "-r", f"{fps:.6f}", "-i", "-",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                "-pix_fmt", "yuv420p", str(silent),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        processed = 0
        try:
            decoder = subprocess.Popen(
                _frame_command(source, width, height, fps),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert decoder.stdout is not None
            assert encoder.stdin is not None
            while True:
                raw = decoder.stdout.read(frame_size)
                if len(raw) < frame_size:
                    break
                frame = Image.frombytes("RGB", (width, height), raw)
                marked, _metadata = embed_image(frame, token, secret, strength=strength)
                encoder.stdin.write(marked.tobytes())
                processed += 1
            decoder.stdout.close()
            decoder_result = decoder.wait(timeout=30)
            if decoder_result:
                raise RuntimeError("ffmpeg não conseguiu decodificar o vídeo de origem")
            if decoder.stderr:
                decoder.stderr.close()
            encoder.stdin.close()
            encoder_result = encoder.wait(timeout=120)
            if encoder_result:
                error = (encoder.stderr.read() if encoder.stderr else b"").decode("utf-8", "replace")
                raise RuntimeError(f"ffmpeg não conseguiu codificar a watermark: {error[-500:]}")
            if encoder.stderr:
                encoder.stderr.close()
            if processed == 0:
                raise RuntimeError("o vídeo não contém frames visuais válidos")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(source),
                    "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac",
                    "-shortest", str(destination),
                ],
                check=True,
                capture_output=True,
            )
        finally:
            if encoder.poll() is None:
                encoder.kill()
    return {"frames_processed": processed, "width": width, "height": height, "fps": fps}


def detect_video(path: Path, secret: str, max_frames: int = 24) -> dict:
    """Sample a video and aggregate independent frame evidence."""
    width, height, fps = _probe(path)
    sample_fps = max(1.0, min(float(fps), max_frames / 6.0))
    scaled_width = min(width, 640)
    scaled_height = max(2, round(height * scaled_width / width))
    if scaled_height % 2:
        scaled_height += 1
    command = [
        "ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={sample_fps:.6f},scale={scaled_width}:{scaled_height}",
        "-frames:v", str(max_frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    frame_size = scaled_width * scaled_height * 3
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    evidences: list[dict] = []
    score_vectors: list[list[float]] = []
    aggregate_layout = None
    try:
        assert process.stdout is not None
        while len(evidences) < max_frames:
            raw = process.stdout.read(frame_size)
            if len(raw) < frame_size:
                break
            frame = Image.frombytes("RGB", (scaled_width, scaled_height), raw)
            try:
                raw_evidence = _decode_scores(frame, secret)
                evidences.append(classify_image_evidence(raw_evidence))
                score_vectors.append(raw_evidence["scores"])
                aggregate_layout = raw_evidence["layout"]
            except ImageWatermarkUnsupported:
                evidences.append(detect_image(frame, secret))
        process.stdout.close()
        result = process.wait(timeout=60)
        if result:
            error = (process.stderr.read() if process.stderr else b"").decode("utf-8", "replace")
            raise RuntimeError(f"ffmpeg não conseguiu amostrar o vídeo: {error[-500:]}")
        if process.stderr:
            process.stderr.close()
    finally:
        if process.poll() is None:
            process.kill()
    supported = [item for item in evidences if item.get("supported")]
    candidates = [item for item in supported if item.get("status") == "CANDIDATE" and item.get("marker")]
    if score_vectors and aggregate_layout is not None:
        aggregate = classify_image_evidence(
            _decode_score_vector(np.mean(np.asarray(score_vectors, dtype=np.float64), axis=0), aggregate_layout)
        )
        return {
            "status": aggregate["status"],
            "marker": aggregate.get("marker"),
            "confidence": aggregate.get("confidence", 0.0),
            "frame_support": round(len(candidates) / max(1, len(supported)), 4),
            "frames_sampled": len(evidences),
            "width": width,
            "height": height,
            "fps": fps,
            "frames": evidences,
        }
    if not candidates:
        status = "INCONCLUSIVE" if any(item.get("status") == "INCONCLUSIVE" for item in supported) else "NOT_FOUND"
        return {"status": status, "frames_sampled": len(evidences), "width": width, "height": height, "fps": fps, "frames": evidences}
    counts: dict[str, list[dict]] = {}
    for item in candidates:
        counts.setdefault(str(item["marker"]), []).append(item)
    marker, marker_evidence = max(counts.items(), key=lambda pair: (len(pair[1]), max(float(item.get("confidence", 0)) for item in pair[1])))
    return {
        "status": "CANDIDATE",
        "marker": marker,
        "confidence": round(sum(float(item.get("confidence", 0)) for item in marker_evidence) / len(marker_evidence), 4),
        "frame_support": round(len(marker_evidence) / max(1, len(supported)), 4),
        "frames_sampled": len(evidences),
        "width": width,
        "height": height,
        "fps": fps,
        "frames": evidences,
    }


def assess_video_robustness(source: Path, watermarked: Path, token: str, secret: str) -> list[dict]:
    """Run independent detection after reproducible media transformations."""
    expected = visual_marker(token)
    transforms = [
        ("controle watermark", "control", None, 24),
        ("original sem marca", "negative-control", None, 24),
        ("borramento leve", "blur-light", "boxblur=1:1", 24),
        ("ruído leve", "noise-light", "noise=alls=4:allf=u:all_seed=1234", 24),
        ("escala + reencode", "resize-reencode", "scale=iw/2:ih/2,scale=iw*2:ih*2", 34),
        ("escala de cinza", "grayscale", "format=gray", 24),
    ]
    checks: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="cdn-watermark-robustness-") as temporary:
        root = Path(temporary)
        for label, filter_id, transform, crf in transforms:
            input_path = source if filter_id == "negative-control" else watermarked
            sample = input_path
            generated = False
            if transform:
                sample = root / f"{filter_id}.mp4"
                command = ["ffmpeg", "-y", "-v", "error", "-i", str(input_path), "-t", "2", "-vf", transform, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(crf), "-pix_fmt", "yuv420p", str(sample)]
                subprocess.run(command, check=True, capture_output=True)
                generated = True
            evidence = detect_video(sample, secret)
            recovered = evidence.get("marker")
            bits_total = len(marker_bits(expected))
            bits_correct = sum(
                int(left == right)
                for left, right in zip(marker_bits(str(recovered or "0")), marker_bits(expected))
            ) if recovered else 0
            is_negative = filter_id == "negative-control"
            checks.append({
                "filter": label,
                "filter_id": filter_id,
                "marker": expected,
                "recovered_marker": recovered or "",
                "confidence": float(evidence.get("confidence", 0.0)),
                "bits_correct": bits_correct,
                "bits_total": bits_total,
                "frame_support": evidence.get("frame_support", 0.0),
                "status": evidence.get("status"),
                "sample_generated": generated,
                "sample_method": "detecção independente em amostra MP4 H.264",
                "confidence_method": "sincronização conhecida + consistência das repetições; autenticidade separada pelo registro do token",
                "survives": (not is_negative) and evidence.get("status") == "CANDIDATE" and recovered == expected,
            })
    return checks
