"""Deterministic held-out metric gate before a port model can be promoted."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def _value(report: dict, section: str, key: str) -> float:
    try:
        return float(report[section][key])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Evaluation report is missing a numeric {section}.{key}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply transparent acceptance thresholds to held-out port-model metrics.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--latency-report", type=Path, required=True,
                        help="GPU benchmark report tied to this exact candidate model")
    parser.add_argument("--calibration-report", type=Path, required=True,
                        help="Held-out confidence-calibration report tied to this model and dataset")
    parser.add_argument("--output", type=Path, default=Path("training/runs/port-yolo11/release-gate.json"))
    parser.add_argument("--min-precision", type=float, default=0.90)
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--min-map50", type=float, default=0.90)
    parser.add_argument("--min-map50-95", type=float, default=0.60)
    parser.add_argument("--min-class-precision", type=float, default=0.85)
    parser.add_argument("--min-class-recall", type=float, default=0.75)
    parser.add_argument("--min-class-map50-95", type=float, default=0.50)
    parser.add_argument("--min-background-images", type=int, default=50)
    parser.add_argument("--max-background-fppi", type=float, default=0.05)
    parser.add_argument("--max-background-positive-rate", type=float, default=0.05)
    parser.add_argument("--max-p95-inference-ms", type=float, default=60.0)
    parser.add_argument("--min-throughput-fps", type=float, default=20.0)
    parser.add_argument("--min-calibration-predictions", type=int, default=500)
    parser.add_argument("--max-expected-calibration-error", type=float, default=0.10)
    parser.add_argument("--max-brier-score", type=float, default=0.20)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    latency = json.loads(args.latency_report.read_text(encoding="utf-8"))
    calibration = json.loads(args.calibration_report.read_text(encoding="utf-8"))
    if report.get("schema") != "sentinel-port-evaluation/1" or not report.get("model_sha256"):
        raise SystemExit("Evaluation report has an unexpected schema or no model SHA-256")
    if latency.get("schema") != "sentinel-inference-benchmark/1":
        raise SystemExit("Latency report has an unexpected schema")
    if str(latency.get("model_sha256", "")).lower() != str(report["model_sha256"]).lower():
        raise SystemExit("Latency report does not belong to the evaluated candidate model")
    if calibration.get("schema") != "sentinel-confidence-calibration/1":
        raise SystemExit("Confidence-calibration report has an unexpected schema")
    if str(calibration.get("model_sha256", "")).lower() != str(report["model_sha256"]).lower():
        raise SystemExit("Confidence-calibration report does not belong to the evaluated model")
    if str(calibration.get("dataset_fingerprint_sha256", "")).lower() != str(
        report.get("dataset_fingerprint_sha256", "")
    ).lower():
        raise SystemExit("Confidence-calibration report does not belong to the evaluated dataset")
    thresholds = {
        "precision": args.min_precision,
        "recall": args.min_recall,
        "map50": args.min_map50,
        "map50_95": args.min_map50_95,
    }
    failures = [
        f"overall.{metric}={_value(report, 'overall', metric):.4f} is below {minimum:.4f}"
        for metric, minimum in thresholds.items()
        if _value(report, "overall", metric) < minimum
    ]
    per_class = report.get("per_class", {})
    for class_name in ("small_boat", "cargo_vessel"):
        for metric, minimum in (("precision", args.min_class_precision),
                                ("recall", args.min_class_recall),
                                ("map50_95", args.min_class_map50_95)):
            try:
                value = float(per_class[metric][class_name])
            except (KeyError, TypeError, ValueError) as exc:
                raise SystemExit(f"Evaluation report is missing per_class.{metric}.{class_name}") from exc
            if value < minimum:
                failures.append(f"per_class.{metric}.{class_name}={value:.4f} is below {minimum:.4f}")
    negatives = report.get("background_negatives", {})
    try:
        background_images = int(negatives["image_count"])
        background_fppi = float(negatives["false_positives_per_image"])
        background_positive_rate = float(negatives["false_positive_image_rate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("Evaluation report is missing background-negative false-alarm metrics") from exc
    if background_images < args.min_background_images:
        failures.append(f"background_negatives.image_count={background_images} is below {args.min_background_images}")
    if background_fppi > args.max_background_fppi:
        failures.append(f"background false_positives_per_image={background_fppi:.4f} exceeds {args.max_background_fppi:.4f}")
    if background_positive_rate > args.max_background_positive_rate:
        failures.append(f"background false_positive_image_rate={background_positive_rate:.4f} exceeds "
                        f"{args.max_background_positive_rate:.4f}")
    try:
        p95_ms = float(latency["latency_ms"]["p95"])
        throughput_fps = float(latency["throughput_fps"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("Latency report is missing latency_ms.p95 or throughput_fps") from exc
    if p95_ms > args.max_p95_inference_ms:
        failures.append(f"latency_ms.p95={p95_ms:.2f} exceeds {args.max_p95_inference_ms:.2f}")
    if throughput_fps < args.min_throughput_fps:
        failures.append(f"throughput_fps={throughput_fps:.2f} is below {args.min_throughput_fps:.2f}")
    try:
        calibration_predictions = int(calibration["prediction_count"])
        expected_calibration_error = float(calibration["expected_calibration_error"])
        brier_score = float(calibration["brier_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("Confidence-calibration report is missing required numeric metrics") from exc
    if calibration_predictions < args.min_calibration_predictions:
        failures.append(
            f"calibration prediction_count={calibration_predictions} is below "
            f"{args.min_calibration_predictions}"
        )
    if expected_calibration_error > args.max_expected_calibration_error:
        failures.append(
            f"expected_calibration_error={expected_calibration_error:.4f} exceeds "
            f"{args.max_expected_calibration_error:.4f}"
        )
    if brier_score > args.max_brier_score:
        failures.append(
            f"brier_score={brier_score:.4f} exceeds {args.max_brier_score:.4f}"
        )
    verdict = {
        "schema": "sentinel-port-release-gate/1",
        "evaluated_report": str(args.report),
        "latency_report": str(args.latency_report),
        "calibration_report": str(args.calibration_report),
        "model_sha256": report["model_sha256"],
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "thresholds": thresholds | {"per_class_precision": args.min_class_precision,
                      "per_class_recall": args.min_class_recall,
                      "per_class_map50_95": args.min_class_map50_95,
                      "min_background_images": args.min_background_images,
                      "max_background_fppi": args.max_background_fppi,
                      "max_background_positive_rate": args.max_background_positive_rate,
                      "max_p95_inference_ms": args.max_p95_inference_ms,
                      "min_throughput_fps": args.min_throughput_fps,
                      "min_calibration_predictions": args.min_calibration_predictions,
                      "max_expected_calibration_error": args.max_expected_calibration_error,
                      "max_brier_score": args.max_brier_score},
        "passed": not failures,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(verdict, indent=2, sort_keys=True), encoding="utf-8")
    if failures:
        print("PORT_MODEL_RELEASE_GATE=FAIL")
        print("\n".join(failures))
        raise SystemExit(1)
    print(f"PORT_MODEL_RELEASE_GATE=PASS report={args.output}")


if __name__ == "__main__":
    main()
