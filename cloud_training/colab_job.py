"""Run a controlled remote-GPU fine-tuning job without promoting a model.

This file is deliberately limited to training and held-out evaluation.  A
candidate produced in a hosted notebook must still be benchmarked on the
deployment GPU and pass the local release gate before it can replace a live
model.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a Sentinel port model on a hosted GPU.")
    parser.add_argument("--workspace", type=Path, default=Path("/content/sentinel"))
    parser.add_argument("--dataset", type=Path, required=True,
                        help="Extracted dataset root containing images/ and labels/")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", type=int, default=-1,
                        help="-1 lets Ultralytics choose a safe GPU batch size")
    parser.add_argument("--base-model", default="yolo11s.pt")
    parser.add_argument("--output", type=Path, default=Path("/content/sentinel-output"))
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    dataset = args.dataset.resolve()
    if not (dataset / "images" / "train").is_dir() or not (dataset / "labels" / "train").is_dir():
        raise SystemExit("Dataset must contain images/train and labels/train before a remote GPU job starts")
    if not (workspace / "training" / "validate_port_dataset.py").is_file():
        raise SystemExit("Upload and extract the Sentinel training bundle before running this job")

    import sys
    sys.path.insert(0, str(workspace / "training"))
    from validate_port_dataset import validate_dataset
    report = validate_dataset(dataset)
    if report.errors:
        raise SystemExit("Dataset validation failed; training was not started:\n" + "\n".join(report.errors))

    data = workspace / "training" / "port.yaml"
    data.write_text(
        "path: " + str(dataset) + "\n"
        "train: images/train\nval: images/val\ntest: images/test\n"
        "names:\n  0: person\n  1: vessel\n  2: vehicle\n  3: container\n",
        encoding="utf-8",
    )
    from ultralytics import YOLO
    model = YOLO(args.base_model)
    run_root = args.output / "runs"
    model.train(data=str(data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=0, project=str(run_root), name="port-yolo11", pretrained=True,
                patience=20, save=True, plots=True, seed=42, deterministic=True)
    candidate = run_root / "port-yolo11" / "weights" / "best.pt"
    if not candidate.is_file():
        raise SystemExit("Training completed without a best.pt candidate")
    metrics = YOLO(str(candidate)).val(data=str(data), imgsz=args.imgsz, device=0, plots=True)
    result = {
        "schema": "sentinel-cloud-training/1",
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "candidate": str(candidate),
        "overall": {"precision": float(metrics.box.mp), "recall": float(metrics.box.mr),
                    "map50": float(metrics.box.map50), "map50_95": float(metrics.box.map)},
        "dataset_fingerprint_sha256": report.dataset_fingerprint_sha256,
        "promotion": "blocked_pending_local_benchmark_and_release_gate",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "cloud-evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    shutil.copy2(candidate, args.output / "best.pt")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
