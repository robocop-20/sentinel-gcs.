"""Generate measured confidence-calibration evidence from held-out predictions.

Input records must be CSV or JSON Lines with ``confidence``, ``correct`` and
``class`` fields. ``correct`` means the prediction was matched to a held-out
ground-truth object under the evaluation protocol that produced the records.
This tool never interprets raw detector confidence as probability on its own.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


def _as_correct(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return 1
    if text in {"0", "false", "no"}:
        return 0
    raise ValueError(f"invalid correct value: {value!r}")


def _validated(record: dict[str, object], *, row_number: int) -> dict[str, object]:
    try:
        confidence = float(record["confidence"])
        correct = _as_correct(record["correct"])
        class_name = str(record["class"]).strip()
    except KeyError as exc:
        raise ValueError(f"record {row_number} is missing {exc.args[0]!r}") from exc
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError(f"record {row_number} confidence must be finite and in [0, 1]")
    if not class_name or len(class_name) > 64:
        raise ValueError(f"record {row_number} class must contain 1..64 characters")
    return {"confidence": confidence, "correct": correct, "class": class_name}


def load_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                records.append(_validated(dict(row), row_number=row_number))
    else:
        with path.open("r", encoding="utf-8") as handle:
            for row_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"record {row_number} must be a JSON object")
                records.append(_validated(value, row_number=row_number))
    if not records:
        raise ValueError("calibration input contains no prediction records")
    return records


def analyze_records(records: Iterable[dict[str, object]], bins: int = 10) -> dict[str, object]:
    if not 2 <= bins <= 100:
        raise ValueError("bins must be between 2 and 100")
    rows = list(records)
    if not rows:
        raise ValueError("at least one prediction record is required")
    buckets: list[list[dict[str, object]]] = [[] for _ in range(bins)]
    for row in rows:
        confidence = float(row["confidence"])
        bucket = min(int(confidence * bins), bins - 1)
        buckets[bucket].append(row)

    calibration_bins: list[dict[str, object]] = []
    ece = 0.0
    mce = 0.0
    for index, bucket_rows in enumerate(buckets):
        count = len(bucket_rows)
        mean_confidence = (
            sum(float(row["confidence"]) for row in bucket_rows) / count if count else None
        )
        empirical_accuracy = (
            sum(int(row["correct"]) for row in bucket_rows) / count if count else None
        )
        gap = (
            abs(mean_confidence - empirical_accuracy)
            if mean_confidence is not None and empirical_accuracy is not None
            else None
        )
        if gap is not None:
            ece += count / len(rows) * gap
            mce = max(mce, gap)
        calibration_bins.append(
            {
                "lower": index / bins,
                "upper": (index + 1) / bins,
                "count": count,
                "mean_confidence": mean_confidence,
                "empirical_accuracy": empirical_accuracy,
                "absolute_gap": gap,
            }
        )

    class_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        class_rows[str(row["class"])].append(row)
    per_class = {
        name: {
            "prediction_count": len(group),
            "mean_confidence": sum(float(row["confidence"]) for row in group) / len(group),
            "empirical_precision": sum(int(row["correct"]) for row in group) / len(group),
            "brier_score": sum(
                (float(row["confidence"]) - int(row["correct"])) ** 2 for row in group
            )
            / len(group),
        }
        for name, group in sorted(class_rows.items())
    }
    return {
        "prediction_count": len(rows),
        "bin_count": bins,
        "expected_calibration_error": ece,
        "maximum_calibration_error": mce,
        "brier_score": sum(
            (float(row["confidence"]) - int(row["correct"])) ** 2 for row in rows
        )
        / len(rows),
        "bins": calibration_bins,
        "per_class": per_class,
    }


def render_svg(analysis: dict[str, object], output: Path) -> None:
    bins = list(analysis["bins"])
    width, height = 1000, 520
    left, top, panel = 70, 55, 380
    gap = 120
    histogram_left = left + panel + gap
    max_count = max((int(item["count"]) for item in bins), default=1) or 1
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f7f8fa"/>',
        '<g font-family="Segoe UI,Arial,sans-serif" fill="#17212b">',
        '<text x="40" y="30" font-size="18" font-weight="600">Sentinel held-out confidence calibration</text>',
        f'<text x="{left}" y="48" font-size="13">Reliability diagram</text>',
        f'<text x="{histogram_left}" y="48" font-size="13">Prediction confidence histogram</text>',
        f'<rect x="{left}" y="{top}" width="{panel}" height="{panel}" fill="#fff" stroke="#98a2ad"/>',
        f'<rect x="{histogram_left}" y="{top}" width="{panel}" height="{panel}" fill="#fff" stroke="#98a2ad"/>',
        f'<line x1="{left}" y1="{top + panel}" x2="{left + panel}" y2="{top}" stroke="#68737f" stroke-dasharray="5 4"/>',
    ]
    bar_width = panel / len(bins)
    points: list[str] = []
    for index, item in enumerate(bins):
        count = int(item["count"])
        mean_conf = item["mean_confidence"]
        accuracy = item["empirical_accuracy"]
        x = histogram_left + index * bar_width + 1
        bar_height = panel * count / max_count
        parts.append(
            f'<rect x="{x:.2f}" y="{top + panel - bar_height:.2f}" '
            f'width="{max(bar_width - 2, 1):.2f}" height="{bar_height:.2f}" fill="#356a88"/>'
        )
        if mean_conf is not None and accuracy is not None:
            px = left + float(mean_conf) * panel
            py = top + panel - float(accuracy) * panel
            points.append(f"{px:.2f},{py:.2f}")
    if points:
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#b34135" stroke-width="3"/>')
        for point in points:
            px, py = point.split(",")
            parts.append(f'<circle cx="{px}" cy="{py}" r="4" fill="#b34135"/>')
    for panel_left in (left, histogram_left):
        parts.extend(
            [
                f'<text x="{panel_left - 8}" y="{top + panel + 22}" font-size="11">0</text>',
                f'<text x="{panel_left + panel - 8}" y="{top + panel + 22}" font-size="11">1</text>',
                f'<text x="{panel_left + panel / 2 - 30}" y="{top + panel + 40}" font-size="12">Confidence</text>',
            ]
        )
    ece = float(analysis["expected_calibration_error"])
    parts.append(
        f'<text x="{left}" y="{height - 22}" font-size="13">ECE {ece:.4f} · '
        f'{int(analysis["prediction_count"])} held-out predictions</text>'
    )
    classes = ", ".join(html.escape(str(name)) for name in analysis["per_class"])
    parts.append(f'<text x="{histogram_left}" y="{height - 22}" font-size="12">Classes: {classes}</text>')
    parts.extend(["</g>", "</svg>"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze held-out detector confidence calibration")
    parser.add_argument("--input", type=Path, required=True, help="CSV or JSONL prediction-match records")
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--report", type=Path, default=Path("reports/vision/confidence-calibration.json"))
    parser.add_argument("--plot", type=Path, default=Path("reports/vision/confidence-calibration.svg"))
    parser.add_argument("--model-sha256", default="")
    parser.add_argument("--dataset-fingerprint-sha256", default="")
    args = parser.parse_args()
    analysis = analyze_records(load_records(args.input), bins=args.bins)
    report = {
        "schema": "sentinel-confidence-calibration/1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "input": str(args.input),
        "model_sha256": args.model_sha256 or None,
        "dataset_fingerprint_sha256": args.dataset_fingerprint_sha256 or None,
        "interpretation": "Empirical held-out calibration; raw detector output remains MODEL CONFIDENCE.",
        **analysis,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    render_svg(analysis, args.plot)
    print(f"CONFIDENCE_CALIBRATION_REPORT={args.report}")
    print(f"CONFIDENCE_CALIBRATION_PLOT={args.plot}")


if __name__ == "__main__":
    main()
