"""Evaluate a candidate port model; this does not promote or deploy it."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
try:
    from .validate_port_dataset import validate_dataset
    from .analyze_confidence import analyze_records, render_svg
except ImportError:  # Direct script execution from the repository root.
    from validate_port_dataset import validate_dataset
    from analyze_confidence import analyze_records, render_svg


CLASS_NAMES = ["person", "vessel", "vehicle", "container"]


def _iou(first: list[float], second: list[float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(right - left, 0.0) * max(bottom - top, 0.0)
    first_area = max(first[2] - first[0], 0.0) * max(first[3] - first[1], 0.0)
    second_area = max(second[2] - second[0], 0.0) * max(second[3] - second[1], 0.0)
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _ground_truth(label_path: Path, width: int, height: int) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"{label_path}:{line_number} must contain five YOLO fields")
        class_id = int(fields[0])
        center_x, center_y, box_width, box_height = map(float, fields[1:])
        values.append(
            {
                "class_id": class_id,
                "box": [
                    (center_x - box_width / 2) * width,
                    (center_y - box_height / 2) * height,
                    (center_x + box_width / 2) * width,
                    (center_y + box_height / 2) * height,
                ],
            }
        )
    return values


def _held_out_calibration_records(
    model,
    dataset_root: Path,
    *,
    confidence: float,
    imgsz: int,
    device: str,
    match_iou: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Match predictions to test labels for empirical confidence calibration."""
    image_dir = dataset_root / "images" / "test"
    label_dir = dataset_root / "labels" / "test"
    images = sorted(
        image for image in image_dir.iterdir()
        if image.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    predictions = model.predict(
        source=[str(path) for path in images],
        conf=confidence,
        imgsz=imgsz,
        device=device,
        verbose=False,
        stream=True,
    )
    records: list[dict[str, object]] = []
    per_class_counts = {
        name: {"ground_truth": 0, "true_positives": 0, "false_positives": 0, "false_negatives": 0}
        for name in CLASS_NAMES
    }
    for image, prediction in zip(images, predictions, strict=True):
        height, width = map(int, prediction.orig_shape)
        truth = _ground_truth(label_dir / f"{image.stem}.txt", width, height)
        for target in truth:
            class_id = int(target["class_id"])
            if 0 <= class_id < len(CLASS_NAMES):
                per_class_counts[CLASS_NAMES[class_id]]["ground_truth"] += 1
        matched_truth: set[int] = set()
        boxes = [] if prediction.boxes is None else prediction.boxes.xyxy.cpu().tolist()
        confidences = [] if prediction.boxes is None else prediction.boxes.conf.cpu().tolist()
        classes = [] if prediction.boxes is None else prediction.boxes.cls.cpu().tolist()
        ranked = sorted(zip(boxes, confidences, classes), key=lambda row: float(row[1]), reverse=True)
        for box, prediction_confidence, raw_class_id in ranked:
            class_id = int(raw_class_id)
            best_index = None
            best_iou = 0.0
            for index, target in enumerate(truth):
                if index in matched_truth or int(target["class_id"]) != class_id:
                    continue
                overlap = _iou(list(map(float, box)), list(map(float, target["box"])))
                if overlap > best_iou:
                    best_index, best_iou = index, overlap
            correct = best_index is not None and best_iou >= match_iou
            if correct:
                matched_truth.add(best_index)
                if 0 <= class_id < len(CLASS_NAMES):
                    per_class_counts[CLASS_NAMES[class_id]]["true_positives"] += 1
            elif 0 <= class_id < len(CLASS_NAMES):
                per_class_counts[CLASS_NAMES[class_id]]["false_positives"] += 1
            records.append(
                {
                    "image": image.name,
                    "class": CLASS_NAMES[class_id] if 0 <= class_id < len(CLASS_NAMES) else str(class_id),
                    "confidence": float(prediction_confidence),
                    "correct": bool(correct),
                    "matched_iou": best_iou,
                    "match_iou_threshold": match_iou,
                }
            )
        for index, target in enumerate(truth):
            class_id = int(target["class_id"])
            if index not in matched_truth and 0 <= class_id < len(CLASS_NAMES):
                per_class_counts[CLASS_NAMES[class_id]]["false_negatives"] += 1
    overall_counts = {
        key: sum(int(counts[key]) for counts in per_class_counts.values())
        for key in ("ground_truth", "true_positives", "false_positives", "false_negatives")
    }
    return records, {
        "ground_truth_match_iou": match_iou,
        "overall": overall_counts,
        "per_class": per_class_counts,
    }


def _per_class_metric(metrics, attribute: str) -> dict[str, float]:
    """Map Ultralytics' reported-class arrays to the fixed Sentinel contract."""
    values = list(getattr(metrics.box, attribute))
    # `maps` is already expanded to model class IDs by Ultralytics. Precision
    # and recall are ordered only by `ap_class_index` and need remapping.
    if attribute == "maps":
        return {name: float(values[index]) if index < len(values) else 0.0
                for index, name in enumerate(CLASS_NAMES)}
    indices = list(getattr(metrics.box, "ap_class_index"))
    by_index = {int(index): float(value) for index, value in zip(indices, values)}
    return {name: by_index.get(index, 0.0) for index, name in enumerate(CLASS_NAMES)}


def _background_metrics(model, dataset_root: Path, *, confidence: float, imgsz: int, device: str) -> dict[str, float | int]:
    """Measure false alarms on explicitly labelled empty test images."""
    image_dir = dataset_root / "images" / "test"
    label_dir = dataset_root / "labels" / "test"
    backgrounds = sorted(
        image for image in image_dir.iterdir()
        if image.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        and (label_dir / f"{image.stem}.txt").is_file()
        and not (label_dir / f"{image.stem}.txt").read_text(encoding="utf-8").strip()
    )
    false_detections = 0
    false_positive_images = 0
    if backgrounds:
        predictions = model.predict(source=[str(path) for path in backgrounds], conf=confidence,
                                    imgsz=imgsz, device=device, verbose=False, stream=True)
        for prediction in predictions:
            count = len(prediction.boxes) if prediction.boxes is not None else 0
            false_detections += count
            false_positive_images += int(count > 0)
    count = len(backgrounds)
    return {"image_count": count, "false_detections": false_detections,
            "false_positive_images": false_positive_images,
            "false_positives_per_image": false_detections / count if count else 0.0,
            "false_positive_image_rate": false_positive_images / count if count else 0.0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path("training/port.yaml"))
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--device", default="0")
    parser.add_argument("--conf", type=float, default=0.35,
                        help="Operating confidence used for held-out false-alarm measurement")
    parser.add_argument("--iou", type=float, default=0.60)
    parser.add_argument("--report", type=Path, default=Path("training/runs/port-yolo11/evaluation.json"))
    parser.add_argument("--calibration-iou", type=float, default=0.50)
    parser.add_argument(
        "--calibration-records",
        type=Path,
        default=Path("reports/vision/held-out-prediction-matches.jsonl"),
    )
    parser.add_argument(
        "--calibration-report",
        type=Path,
        default=Path("reports/vision/confidence-calibration.json"),
    )
    parser.add_argument(
        "--calibration-plot",
        type=Path,
        default=Path("reports/vision/confidence-calibration.svg"),
    )
    parser.add_argument("--calibration-bins", type=int, default=10)
    args = parser.parse_args()

    dataset_report = validate_dataset(Path("training/datasets/port"))
    if dataset_report.errors:
        raise SystemExit("Refusing evaluation: the local training dataset no longer passes validation")

    from ultralytics import YOLO
    model = YOLO(str(args.model))
    metrics = model.val(data=str(args.data), imgsz=args.imgsz, device=args.device,
                        conf=args.conf, iou=args.iou, plots=True)
    background = _background_metrics(model, Path("training/datasets/port"), confidence=args.conf,
                                     imgsz=args.imgsz, device=args.device)
    calibration_records, object_counts = _held_out_calibration_records(
        model,
        Path("training/datasets/port"),
        confidence=args.conf,
        imgsz=args.imgsz,
        device=args.device,
        match_iou=args.calibration_iou,
    )
    args.calibration_records.parent.mkdir(parents=True, exist_ok=True)
    args.calibration_records.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in calibration_records),
        encoding="utf-8",
    )
    model_sha256 = hashlib.sha256(args.model.read_bytes()).hexdigest()
    calibration_analysis = analyze_records(calibration_records, bins=args.calibration_bins)
    calibration_report = {
        "schema": "sentinel-confidence-calibration/1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "input": str(args.calibration_records),
        "model_sha256": model_sha256,
        "dataset_fingerprint_sha256": dataset_report.dataset_fingerprint_sha256,
        "ground_truth_match_iou": args.calibration_iou,
        "interpretation": "Empirical held-out prediction calibration; recall is measured separately.",
        **calibration_analysis,
    }
    args.calibration_report.parent.mkdir(parents=True, exist_ok=True)
    args.calibration_report.write_text(
        json.dumps(calibration_report, indent=2, sort_keys=True), encoding="utf-8"
    )
    render_svg(calibration_analysis, args.calibration_plot)
    overall_precision = float(metrics.box.mp)
    overall_recall = float(metrics.box.mr)
    per_class_precision = _per_class_metric(metrics, "p")
    per_class_recall = _per_class_metric(metrics, "r")
    report = {
        "schema": "sentinel-port-evaluation/1",
        "evaluated_at_utc": datetime.now(UTC).isoformat(),
        "model_path": str(args.model),
        "model_sha256": model_sha256,
        "data": str(args.data),
        "operating_point": {"confidence": args.conf, "iou": args.iou, "imgsz": args.imgsz},
        "dataset_fingerprint_sha256": dataset_report.dataset_fingerprint_sha256,
        "overall": {
            "precision": overall_precision,
            "recall": overall_recall,
            "f1": (
                2 * overall_precision * overall_recall / (overall_precision + overall_recall)
                if overall_precision + overall_recall
                else 0.0
            ),
            "map50": float(metrics.box.map50),
            "map50_95": float(metrics.box.map),
        },
        "per_class": {
            "precision": per_class_precision,
            "recall": per_class_recall,
            "f1": {
                name: (
                    2 * per_class_precision[name] * per_class_recall[name]
                    / (per_class_precision[name] + per_class_recall[name])
                    if per_class_precision[name] + per_class_recall[name]
                    else 0.0
                )
                for name in CLASS_NAMES
            },
            "map50": _per_class_metric(metrics, "ap50"),
            "map50_95": _per_class_metric(metrics, "maps"),
        },
        "held_out_object_counts": object_counts,
        "background_negatives": background,
        "validation_artifacts": {
            "ultralytics_plot_directory": str(getattr(metrics, "save_dir", "")),
            "expected_plots": [
                "confusion_matrix.png",
                "confusion_matrix_normalized.png",
                "PR_curve.png",
                "P_curve.png",
                "R_curve.png",
                "F1_curve.png",
            ],
        },
        "confidence_calibration_input": {
            "path": str(args.calibration_records),
            "prediction_count": len(calibration_records),
            "ground_truth_match_iou": args.calibration_iou,
            "scope": "prediction calibration only; recall remains reported separately",
        },
        "confidence_calibration_report": str(args.calibration_report),
        "confidence_calibration_plot": str(args.calibration_plot),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"PORT_MODEL_EVALUATION_REPORT={args.report}")
    print(f"PORT_MODEL_METRICS={json.dumps(report['overall'], sort_keys=True)}")


if __name__ == "__main__":
    main()
