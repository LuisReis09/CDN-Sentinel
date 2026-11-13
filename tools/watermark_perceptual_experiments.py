"""Compare watermark visibility and authenticated recovery under equal encoding.

The script writes real MP4 variants to the ignored generated-media directory and
prints a JSON report. It deliberately re-encodes the unmarked control with the
same FFmpeg settings used for every marked candidate before computing quality.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.watermark_service import WatermarkService
from utils.dct_watermark import detect_image_dct
from utils.image_watermark import (
    ADAPTIVE_MASK_FLOOR,
    CARRIER_BLOCK,
    DATA_BITS,
    DATA_REPETITIONS,
    SYNC_BITS,
    _box_mean,
    detect_image,
    marker_bits,
    visual_marker,
)
from utils.video import get_video_asset
from utils.video_watermark import VIDEO_STRENGTH, _probe, detect_video, embed_video, transcode_video


def _read_frames(path: Path, max_frames: int = 24) -> list[np.ndarray]:
    width, height, _fps = _probe(path)
    process = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-frames:v", str(max_frames),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    frame_size = width * height * 3
    return [
        np.frombuffer(process.stdout[offset:offset + frame_size], dtype=np.uint8).reshape(height, width, 3).copy()
        for offset in range(0, len(process.stdout) - frame_size + 1, frame_size)
    ]


def _luma(frame: np.ndarray) -> np.ndarray:
    rgb = frame.astype(np.float64)
    return 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]


def _ssim(left: np.ndarray, right: np.ndarray) -> float:
    """Windowed SSIM on luminance, Gaussian 11x11, data range 255."""
    from scipy.ndimage import gaussian_filter

    if left.shape != right.shape or min(left.shape) < 11:
        raise ValueError("SSIM requires aligned images at least 11 pixels wide")
    left, right = left.astype(np.float64), right.astype(np.float64)
    kwargs = {"sigma": 1.5, "truncate": 3.5, "mode": "reflect"}
    mean_left = gaussian_filter(left, **kwargs)
    mean_right = gaussian_filter(right, **kwargs)
    correction = 121.0 / 120.0
    var_left = correction * (gaussian_filter(left * left, **kwargs) - mean_left * mean_left)
    var_right = correction * (gaussian_filter(right * right, **kwargs) - mean_right * mean_right)
    covariance = correction * (gaussian_filter(left * right, **kwargs) - mean_left * mean_right)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    numerator = (2 * mean_left * mean_right + c1) * (2 * covariance + c2)
    denominator = (mean_left**2 + mean_right**2 + c1) * (var_left + var_right + c2)
    return float(np.mean((numerator / np.maximum(denominator, 1e-12))[5:-5, 5:-5]))


def _downsample(values: np.ndarray, scale: int) -> np.ndarray:
    image = Image.fromarray(np.uint8(np.clip(values, 0, 255)), "L")
    width = max(1, values.shape[1] // scale)
    height = max(1, values.shape[0] // scale)
    return np.asarray(image.resize((width, height), Image.Resampling.LANCZOS), dtype=np.float64)


def _ms_ssim(left: np.ndarray, right: np.ndarray) -> float:
    scales = [_ssim(_downsample(left, scale), _downsample(right, scale)) for scale in (1, 2, 4)]
    return float(math.prod(max(0.0, value) for value in scales) ** (1.0 / len(scales)))


def _quality(reference: list[np.ndarray], candidate: list[np.ndarray]) -> dict:
    count = min(len(reference), len(candidate))
    if not count:
        return {"frames": 0}
    psnr_values: list[float] = []
    ssim_values: list[float] = []
    ms_ssim_values: list[float] = []
    region_means: list[float] = []
    uniform_means: list[float] = []
    dark_means: list[float] = []
    delta_pixels: list[float] = []
    for left_rgb, right_rgb in zip(reference[:count], candidate[:count]):
        left = left_rgb.astype(np.float64)
        right = right_rgb.astype(np.float64)
        mse = float(np.mean((left - right) ** 2))
        psnr_values.append(99.0 if mse == 0 else 10.0 * math.log10((255.0**2) / mse))
        left_luma, right_luma = _luma(left_rgb), _luma(right_rgb)
        ssim_values.append(_ssim(left_luma, right_luma))
        ms_ssim_values.append(_ms_ssim(left_luma, right_luma))
        delta = np.abs(right_luma - left_luma)
        delta_pixels.extend(delta.ravel()[:: max(1, delta.size // 10000)].tolist())
        height, width = delta.shape
        regions = [
            delta[y0:y1, x0:x1].mean()
            for y0, y1 in ((0, height // 2), (height // 2, height))
            for x0, x1 in ((0, width // 2), (width // 2, width))
        ]
        region_means.extend(regions)
        source_luma = left_luma
        local_mean = _box_mean(source_luma, radius=2)
        local_variance = np.maximum(_box_mean(source_luma * source_luma, radius=2) - local_mean * local_mean, 0.0)
        uniform_means.append(float(delta[local_variance < 10.0].mean()) if np.any(local_variance < 10.0) else 0.0)
        dark_means.append(float(delta[source_luma < 32.0].mean()) if np.any(source_luma < 32.0) else 0.0)
    return {
        "frames": count,
        "psnr_db": round(float(np.mean(psnr_values)), 4),
        "ssim": round(float(np.mean(ssim_values)), 6),
        "ms_ssim": round(float(np.mean(ms_ssim_values)), 6),
        "region_mean_abs_luma_max": round(float(np.max(region_means)), 4),
        "region_mean_abs_luma_p95": round(float(np.percentile(region_means, 95)), 4),
        "uniform_region_mean_abs_luma": round(float(np.mean(uniform_means)), 4),
        "dark_region_mean_abs_luma": round(float(np.mean(dark_means)), 4),
        "pixels_abs_delta_ge_2_rate": round(float(np.mean(np.asarray(delta_pixels) >= 2.0)), 6),
    }


def _transform(source: Path, destination: Path, kind: str) -> None:
    filters = {
        "h264_crf34": None,
        "blur": "boxblur=1:1",
        "noise": "noise=alls=4:allf=u:all_seed=1234",
        "resize": "scale=iw/2:ih/2,scale=iw*2:ih*2",
    }
    command = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-an"]
    if filters[kind]:
        command.extend(["-vf", filters[kind]])
    command.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-pix_fmt", "yuv420p", str(destination)])
    subprocess.run(command, check=True, capture_output=True)


def _detection(service: WatermarkService, path: Path, adaptive: bool, algorithm: str, dct_step: float = 10.0) -> dict:
    evidence = service.detect_video(path, adaptive=adaptive, algorithm=algorithm, dct_step=dct_step)
    return {
        "status": evidence.get("status"),
        "confidence": evidence.get("confidence", 0.0),
        "marker": evidence.get("marker"),
        "visual_hamming_distance": evidence.get("visual_hamming_distance", 0),
        "frames_sampled": evidence.get("frames_sampled", 0),
    }


def _jpeg_image_detection(service: WatermarkService, frame: np.ndarray, token: str, secret: str, algorithm: str, dct_step: float = 10.0) -> dict:
    image = Image.fromarray(frame, "RGB")
    temporary_path: Path | None = None
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temporary:
        temporary_path = Path(temporary.name)
        image.save(temporary, format="JPEG", quality=80)
    try:
        jpeg = Image.open(temporary_path).convert("RGB")
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    if algorithm == "dct":
        evidence = detect_image_dct(jpeg, secret, step=dct_step)
    else:
        evidence = detect_image(jpeg, secret, adaptive=True)
    expected = visual_marker(token)
    return {
        "status": evidence.get("status"),
        "marker_match": evidence.get("marker") == expected,
        "bits_correct": sum(a == b for a, b in zip(marker_bits(str(evidence.get("marker") or "")), marker_bits(expected))),
        "bits_total": len(marker_bits(expected)),
    }


def run(video_id: str = "cdn_sentinel_demo") -> dict:
    source, _content_type = get_video_asset(video_id, "original")
    output_root = Path(__file__).resolve().parents[1] / "data" / "media" / "generated" / "perceptual-experiments"
    output_root.mkdir(parents=True, exist_ok=True)
    service = WatermarkService("perceptual-experiment-secret")
    token, _claim = service.issue("experiment-client", "experiment-server", 0, video_id)
    configurations = [
        {"name": "baseline-current-strength16", "algorithm": "adaptive-spread", "adaptive": False, "strength": 16.0},
        *[
            {"name": f"adaptive-spread-strength{strength:g}", "algorithm": "adaptive-spread", "adaptive": True, "strength": strength}
            for strength in (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 20.0, 24.0, 28.0)
        ],
        *[
            {"name": f"dct-step{step:g}", "algorithm": "dct", "adaptive": False, "strength": step}
            for step in (10.0, 18.0, 22.0)
        ],
    ]
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="cdn-watermark-experiment-") as temporary:
        temporary_root = Path(temporary)
        control = temporary_root / "control.mp4"
        transcode_video(source, control, crf=24, preset="veryfast")
        reference_frames = _read_frames(control)
        for configuration in configurations:
            name = configuration["name"]
            marked = output_root / f"{name}.mp4"
            embed_video(
                source,
                marked,
                token,
                service.secret_key,
                strength=configuration["strength"],
                adaptive=configuration["adaptive"],
                algorithm=configuration["algorithm"],
            )
            marked_frames = _read_frames(marked)
            dct_step = configuration["strength"] if configuration["algorithm"] == "dct" else 10.0
            detection = _detection(service, marked, configuration["adaptive"], configuration["algorithm"], dct_step)
            negative_control = _detection(service, source, configuration["adaptive"], configuration["algorithm"], dct_step)
            transforms: dict[str, dict] = {}
            for transform_name in ("h264_crf34", "blur", "noise", "resize"):
                transformed = temporary_root / f"{name}-{transform_name}.mp4"
                _transform(marked, transformed, transform_name)
                transforms[transform_name] = _detection(service, transformed, configuration["adaptive"], configuration["algorithm"], dct_step)
            jpeg = _jpeg_image_detection(service, marked_frames[0], token, service.secret_key, configuration["algorithm"], dct_step)
            results.append({
                **configuration,
                "quality_vs_same_crf_control": _quality(reference_frames, marked_frames),
                "detection": detection,
                "negative_control": {
                    **negative_control,
                    "false_positive": negative_control["status"] == "VALID",
                },
                "jpeg_q80_first_frame": jpeg,
                "transforms": transforms,
                "marker": visual_marker(token),
            })
    return {
        "video_id": video_id,
        "source": str(source),
        "encoding": {"codec": "libx264", "preset": "veryfast", "crf": 24, "pix_fmt": "yuv420p"},
        "token_marker_bits": len(marker_bits(visual_marker(token))),
        "watermark_parameters": {
            "video_strength": VIDEO_STRENGTH,
            "adaptive_mask_floor": ADAPTIVE_MASK_FLOOR,
            "carrier_block": CARRIER_BLOCK,
            "data_bits": DATA_BITS,
            "sync_bits": SYNC_BITS,
            "data_repetitions": DATA_REPETITIONS,
        },
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", default="cdn_sentinel_demo")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = run(args.video_id)
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
