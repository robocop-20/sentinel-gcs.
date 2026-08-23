"""Benchmark a candidate model locally before it can be released.

This does not measure detector accuracy.  It measures single-frame inference
on the actual deployment GPU and records a model-bound report for the release
gate.  No image is uploaded or modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[position]


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure local single-frame YOLO inference latency.")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--images", type=Path, default=Path("training/datasets/port/images/test"))
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--device", default="0")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--report", type=Path, default=Path("training/runs/port-yolo11/inference-benchmark.json"))
    args = parser.parse_args()
    if not args.model.is_file():
        raise SystemExit(f"Candidate model does not exist: {args.model}")
    images = sorted(path for path in args.images.rglob("*") if path.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise SystemExit(f"No held-out benchmark images under {args.images}")
    from ultralytics import YOLO
    import torch
    model = YOLO(str(args.model))
    selected = [images[index % len(images)] for index in range(max(args.samples, 1))]
    use_cuda = str(args.device).lower() not in {"cpu", "-1"} and torch.cuda.is_available()
    def run(image: Path) -> float:
        if use_cuda:
            torch.cuda.synchronize()
        started = time.perf_counter()
        model.predict(str(image), imgsz=args.imgsz, device=args.device, verbose=False)
        if use_cuda:
            torch.cuda.synchronize()
        return (time.perf_counter() - started) * 1000
    for index in range(max(args.warmup, 0)):
        run(images[index % len(images)])
    samples_ms = [run(image) for image in selected]
    mean_ms = statistics.fmean(samples_ms)
    report = {
        "schema": "sentinel-inference-benchmark/1",
        "benchmarked_at_utc": datetime.now(UTC).isoformat(),
        "model_path": str(args.model),
        "model_sha256": sha256_file(args.model),
        "images_path": str(args.images),
        "images_sampled": len(selected),
        "imgsz": args.imgsz,
        "device": args.device,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device": torch.cuda.get_device_name(0) if use_cuda else None,
        "latency_ms": {"mean": round(mean_ms, 3), "p50": round(percentile(samples_ms, .50), 3),
                       "p95": round(percentile(samples_ms, .95), 3), "max": round(max(samples_ms), 3)},
        "throughput_fps": round(1000 / mean_ms, 3),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"PORT_MODEL_BENCHMARK_REPORT={args.report}")
    print(f"PORT_MODEL_BENCHMARK_P95_MS={report['latency_ms']['p95']}")


if __name__ == "__main__":
    main()
