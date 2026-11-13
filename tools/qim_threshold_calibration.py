"""Collect blind negative score distributions before adjusting QIM gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.video_watermark import detect_video


def run(dataset_root: Path, count: int = 32, step: float = 20.0, offset: int = 0, algorithm: str = "qim2") -> dict:
    if algorithm not in {"qim2", "qim3"}:
        raise ValueError("algorithm must be qim2 or qim3")
    files = sorted(path for path in dataset_root.rglob("*.mp4") if path.is_file())[offset:offset + count]
    rows = []
    for source in files:
        try:
            result = detect_video(source, "calibration-secret-with-entropy-2026", algorithm=algorithm, max_frames=8, qim_step=step)
            rows.append({"video": str(source.relative_to(dataset_root)), "status": result.get("status"), "score": result.get("confidence", 0.0), "sync": result.get("sync_confidence", 0.0)})
        except Exception as exc:
            rows.append({"video": str(source.relative_to(dataset_root)), "status": "ERROR", "error": str(exc)[-200:]})
    valid = [row for row in rows if row["status"] != "ERROR"]
    return {"algorithm": algorithm, "count": len(valid), "offset": offset, "step": step, "max_negative_score": max((row["score"] for row in valid), default=None), "candidate_count": sum(row["status"] == "CANDIDATE" for row in valid), "rows": rows, "calibration_only": offset == 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=Path("data/datasets/youtube_clipped_videos"))
    parser.add_argument("--count", type=int, default=32)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--qim-step", type=float, default=20.0)
    parser.add_argument("--algorithm", choices=("qim2", "qim3"), default="qim2")
    args = parser.parse_args()
    result = run(args.dataset_root, args.count, args.qim_step, args.offset, args.algorithm)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
