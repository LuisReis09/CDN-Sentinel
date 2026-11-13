"""Streaming video adapter for the independent image watermark detector."""

from __future__ import annotations

import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

from utils.dct_watermark import _decode_scores as _decode_dct_scores, detect_image_dct, embed_image_dct
from utils.qim_watermark import (
    QIM_STEP, QIM3_STEP, _decode_score_vector as _decode_qim_score_vector,
    _decode_qim3_score_vector, detect_image_qim, detect_image_qim3,
    embed_image_qim, embed_image_qim3,
)
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


VIDEO_STRENGTH = 24.0
DETECTION_WIDTH = 640


def transcode_video(source: Path, destination: Path, crf: int = 24, preset: str = "veryfast") -> dict:
    """Encode a no-watermark control under the same conditions as embed_video."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", preset,
            "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(destination),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    return {"crf": crf, "preset": preset}


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
        timeout=15,
    )
    # MPEG-TS can report the same video stream more than once.  Parse a
    # complete stream row instead of treating all stdout as one CSV record.
    for line in result.stdout.splitlines():
        fields = line.strip().split(",")
        if len(fields) != 3 or "/" not in fields[2]:
            continue
        try:
            width, height = int(fields[0]), int(fields[1])
            numerator, denominator = (int(value) for value in fields[2].split("/", 1))
        except ValueError:
            continue
        if width > 0 and height > 0 and numerator > 0 and denominator > 0:
            return width, height, numerator / denominator
    raise ValueError("metadados de vídeo inválidos")


def probe_video_limits(path: Path) -> dict:
    """Return bounded media metadata for API resource validation."""
    width, height, fps = _probe(path)
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        duration = 0.0
    return {"width": width, "height": height, "fps": fps, "duration_seconds": duration}


def _frame_count(path: Path, fps: float) -> int:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=nb_read_frames,duration", "-of", "default=nw=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    values = [value.strip() for value in result.stdout.splitlines() if value.strip()]
    fields = {
        key: value
        for line in values
        if "=" in line
        for key, value in [line.split("=", 1)]
    }
    try:
        count = int(float(fields.get("nb_read_frames", "0")))
    except ValueError:
        count = 0
    if count > 0:
        return count
    for value in values:
        try:
            count = int(float(value))
        except ValueError:
            continue
        if count > 0:
            return count
    for value in values:
        try:
            duration = float(value)
        except ValueError:
            continue
        if duration > 0:
            return max(1, round(duration * fps))
    try:
        duration = float(fields.get("duration", "0"))
    except ValueError:
        duration = 0.0
    if duration > 0:
        return max(1, round(duration * fps))
    return 1


def _frame_command(path: Path, width: int, height: int, fps: float) -> list[str]:
    return [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]


def embed_video(
    source: Path,
    destination: Path,
    token: str,
    secret: str,
    strength: float | None = None,
    adaptive: bool = True,
    algorithm: str = "adaptive-spread",
    diagnostic_residual_path: Path | None = None,
) -> dict:
    """Watermark a video frame-by-frame with bounded memory usage."""
    strength = strength if strength is not None else (QIM3_STEP if algorithm == "qim3" else QIM_STEP if algorithm == "qim2" else VIDEO_STRENGTH)
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
            stderr=subprocess.DEVNULL,
        )
        residual_encoder = None
        if diagnostic_residual_path is not None:
            diagnostic_residual_path.parent.mkdir(parents=True, exist_ok=True)
            residual_encoder = subprocess.Popen(
                [
                    "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{width}x{height}", "-r", f"{fps:.6f}", "-i", "-",
                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(diagnostic_residual_path),
                ],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        processed = 0
        try:
            decoder = subprocess.Popen(
                _frame_command(source, width, height, fps),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            assert decoder.stdout is not None
            assert encoder.stdin is not None
            while True:
                raw = decoder.stdout.read(frame_size)
                if len(raw) < frame_size:
                    break
                frame = Image.frombytes("RGB", (width, height), raw)
                if algorithm == "dct":
                    marked, _metadata = embed_image_dct(frame, token, secret, step=strength)
                elif algorithm == "qim2":
                    marked, _metadata = embed_image_qim(frame, token, secret, step=strength)
                elif algorithm == "qim3":
                    marked, _metadata = embed_image_qim3(frame, token, secret, step=strength)
                elif algorithm == "adaptive-spread":
                    marked, _metadata = embed_image(frame, token, secret, strength=strength, adaptive=adaptive)
                else:
                    raise ValueError(f"algoritmo visual de vídeo não suportado: {algorithm}")
                encoder.stdin.write(marked.tobytes())
                if residual_encoder is not None:
                    assert residual_encoder.stdin is not None
                    residual = ImageChops.difference(frame, marked).convert("L")
                    residual = residual.point(lambda value: min(255, value * 8)).convert("RGB")
                    residual_encoder.stdin.write(residual.tobytes())
                processed += 1
            decoder.stdout.close()
            decoder_result = decoder.wait(timeout=30)
            if decoder_result:
                raise RuntimeError("ffmpeg não conseguiu decodificar o vídeo de origem")
            encoder.stdin.close()
            encoder_result = encoder.wait(timeout=120)
            if encoder_result:
                raise RuntimeError("ffmpeg não conseguiu codificar a watermark")
            if residual_encoder is not None:
                assert residual_encoder.stdin is not None
                residual_encoder.stdin.close()
                if residual_encoder.wait(timeout=120):
                    raise RuntimeError("ffmpeg failed to encode pre-codec diagnostic residual")
            if processed == 0:
                raise RuntimeError("o vídeo não contém frames visuais válidos")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(source),
                    "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac",
                    str(destination),
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )
        finally:
            if encoder.poll() is None:
                encoder.kill()
            if residual_encoder is not None and residual_encoder.poll() is None:
                residual_encoder.kill()
    return {"frames_processed": processed, "width": width, "height": height, "fps": fps}


def detect_video(
    path: Path,
    secret: str,
    max_frames: int = 24,
    adaptive: bool = True,
    algorithm: str = "adaptive-spread",
    dct_step: float = 10.0,
    qim_step: float | None = None,
) -> dict:
    """Sample the whole video and aggregate independent frame evidence.

    Detection uses one canonical 640px-wide geometry. Embedding can happen at
    320p, 720p or 1080p, but both the received frame and the keyed carrier are
    compared after the same deterministic normalization. The frame indices are
    distributed over the complete duration, which avoids making a decision
    from only the opening seconds of a long asset.
    """
    qim_step = qim_step if qim_step is not None else (QIM3_STEP if algorithm == "qim3" else QIM_STEP)
    width, height, fps = _probe(path)
    total_frames = _frame_count(path, fps)
    sample_count = min(max_frames, total_frames)
    indices = np.linspace(0, max(0, total_frames - 1), sample_count, dtype=np.int64).tolist()
    select_expression = "+".join(f"eq(n,{int(index)})" for index in indices) or "eq(n,0)"
    detection_width = DETECTION_WIDTH
    detection_height = max(2, round(height * detection_width / width))
    if detection_height % 2:
        detection_height += 1
    command = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", f"select='{select_expression}',scale={detection_width}:{detection_height}",
        "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    frame_size = detection_width * detection_height * 3
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    watchdog = threading.Timer(120.0, process.kill)
    watchdog.daemon = True
    watchdog.start()
    evidences: list[dict] = []
    score_vectors: list[list[float]] = []
    aggregate_layout = None
    try:
        assert process.stdout is not None
        while len(evidences) < max_frames:
            raw = process.stdout.read(frame_size)
            if len(raw) < frame_size:
                break
            frame = Image.frombytes("RGB", (detection_width, detection_height), raw)
            try:
                if algorithm == "dct":
                    raw_evidence = _decode_dct_scores(frame, secret, step=dct_step)
                elif algorithm in {"qim2", "qim3"}:
                    raw_evidence = (detect_image_qim3 if algorithm == "qim3" else detect_image_qim)(frame, secret, step=qim_step)
                    evidences.append({key: value for key, value in raw_evidence.items() if key != "scores"})
                    if raw_evidence.get("supported"):
                        score_vectors.append(raw_evidence["scores"])
                        aggregate_layout = True
                    continue
                else:
                    raw_evidence = _decode_scores(frame, secret, adaptive=adaptive)
                evidences.append(classify_image_evidence(raw_evidence))
                score_vectors.append(raw_evidence["scores"])
                aggregate_layout = raw_evidence["layout"]
            except ImageWatermarkUnsupported:
                if algorithm == "dct":
                    evidences.append(detect_image_dct(frame, secret, step=dct_step))
                else:
                    evidences.append(detect_image(frame, secret, adaptive=adaptive))
        process.stdout.close()
        result = process.wait(timeout=60)
        if result:
            raise RuntimeError("ffmpeg não conseguiu amostrar o vídeo")
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
    supported = [item for item in evidences if item.get("supported")]
    candidates = [item for item in supported if item.get("status") == "CANDIDATE" and item.get("marker")]
    if score_vectors and aggregate_layout is not None:
        weights = np.asarray(
            [max(0.25, float(item.get("confidence", 0.0))) for item in evidences[:len(score_vectors)]],
            dtype=np.float64,
        )
        if len(weights) != len(score_vectors):
            weights = np.ones(len(score_vectors), dtype=np.float64)
        weights /= max(float(weights.sum()), 1e-9)
        averaged_scores = np.average(np.asarray(score_vectors, dtype=np.float64), axis=0, weights=weights)
        aggregate = (
            _decode_qim_score_vector(averaged_scores) if algorithm == "qim2" else
            _decode_qim3_score_vector(averaged_scores) if algorithm == "qim3" else
            classify_image_evidence(_decode_score_vector(averaged_scores, aggregate_layout))
        )
        # Compression can corrupt different coded bits in different frames,
        # making a score-vector average less reliable than a consensus of the
        # independently decoded frame markers. Keep the aggregate metrics, but
        # use a supported marker consensus when at least two frames agree.
        if candidates and aggregate["status"] != "CANDIDATE":
            counts: dict[str, list[dict]] = {}
            for item in candidates:
                counts.setdefault(str(item["marker"]), []).append(item)
            consensus_marker, consensus_items = max(
                counts.items(),
                key=lambda pair: (len(pair[1]), max(float(item.get("confidence", 0.0)) for item in pair[1])),
            )
            if len(consensus_items) >= 2:
                aggregate["status"] = "CANDIDATE"
                aggregate["marker"] = consensus_marker
                aggregate["confidence"] = round(
                    sum(float(item.get("confidence", 0.0)) for item in consensus_items) / len(consensus_items),
                    4,
                )
        return {
            "status": aggregate["status"],
            "marker": aggregate.get("marker"),
            "confidence": aggregate.get("confidence", 0.0),
            "sync_confidence": aggregate.get("sync_confidence", 0.0),
            "ecc": aggregate.get("ecc", "none"),
            "ecc_status": aggregate.get("ecc_status"),
            "ecc_corrected_bits": aggregate.get("ecc_corrected_bits", 0),
            "scores": aggregate.get("scores"),
            "repetition_consistency": aggregate.get("repetition_consistency", 0.0),
            "frame_support": round(len(candidates) / max(1, len(supported)), 4),
            "frames_sampled": len(evidences),
            "width": width,
            "height": height,
            "fps": fps,
            "detection_width": detection_width,
            "detection_height": detection_height,
            "temporal_sampling": "uniform-over-full-video",
            "sampled_frame_indices": indices,
            "frames": evidences,
        }
    if not candidates:
        status = "INCONCLUSIVE" if any(item.get("status") == "INCONCLUSIVE" for item in supported) else "NOT_FOUND"
        return {
            "status": status,
            "frames_sampled": len(evidences),
            "width": width,
            "height": height,
            "fps": fps,
            "detection_width": detection_width,
            "detection_height": detection_height,
            "temporal_sampling": "uniform-over-full-video",
            "sampled_frame_indices": indices,
            "frames": evidences,
        }
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
        "detection_width": detection_width,
        "detection_height": detection_height,
        "temporal_sampling": "uniform-over-full-video",
        "sampled_frame_indices": indices,
        "frames": evidences,
    }


def assess_video_robustness(
    source: Path,
    watermarked: Path,
    token: str,
    secret: str,
    adaptive: bool = True,
    algorithm: str = "adaptive-spread",
    dct_step: float = 10.0,
) -> list[dict]:
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
            evidence = detect_video(sample, secret, adaptive=adaptive, algorithm=algorithm, dct_step=dct_step)
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
                "sample_method": f"detecção independente em amostra MP4 H.264 ({algorithm})",
                "confidence_method": "sincronização conhecida + consistência das repetições; autenticidade separada pelo registro do token",
                "survives": (not is_negative) and evidence.get("status") == "CANDIDATE" and recovered == expected,
            })
    return checks
