"""Validate a local YOLO-format port-surveillance dataset before training.

The validator never uploads images or labels. It rejects malformed annotations
so that an incorrectly labelled port dataset is not silently trained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path


CLASS_COUNT = 2
CLASS_NAMES = ("small_boat", "cargo_vessel")
SPLITS = ("train", "val", "test")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class DatasetReport:
    image_count: int = 0
    labelled_image_count: int = 0
    background_image_count: int = 0
    class_counts: Counter = field(default_factory=Counter)
    split_image_counts: Counter = field(default_factory=Counter)
    split_background_counts: Counter = field(default_factory=Counter)
    split_class_counts: dict[str, Counter] = field(default_factory=lambda: {split: Counter() for split in SPLITS})
    dataset_fingerprint_sha256: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_label(path: Path, report: DatasetReport, split: str) -> list[str]:
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        values = line.split()
        if len(values) != 5:
            errors.append(f"{path}:{line_number}: expected 5 YOLO values")
            continue
        try:
            class_id = int(values[0])
            coordinates = [float(value) for value in values[1:]]
        except ValueError:
            errors.append(f"{path}:{line_number}: non-numeric annotation")
            continue
        if not 0 <= class_id < CLASS_COUNT:
            errors.append(f"{path}:{line_number}: class {class_id} outside 0..{CLASS_COUNT - 1}")
        center_x, center_y, width, height = coordinates
        if not (0 <= center_x <= 1 and 0 <= center_y <= 1 and 0 < width <= 1 and 0 < height <= 1):
            errors.append(f"{path}:{line_number}: coordinates must be normalised YOLO values")
        else:
            report.class_counts[class_id] += 1
            report.split_class_counts[split][class_id] += 1
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dataset(dataset_root: Path) -> DatasetReport:
    report = DatasetReport()
    split_hashes: dict[str, set[str]] = {split: set() for split in SPLITS}
    for split in SPLITS:
        image_dir = dataset_root / "images" / split
        label_dir = dataset_root / "labels" / split
        if not image_dir.is_dir() or not label_dir.is_dir():
            report.errors.append(f"{split}: expected {image_dir} and {label_dir}")
            continue
        for image in image_dir.iterdir():
            if image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            report.image_count += 1
            report.split_image_counts[split] += 1
            image_hash = _sha256(image)
            for other_split, hashes in split_hashes.items():
                if other_split != split and image_hash in hashes:
                    report.errors.append(f"{image}: duplicate image across {other_split}/{split} splits")
            split_hashes[split].add(image_hash)
            label = label_dir / f"{image.stem}.txt"
            if not label.is_file():
                report.errors.append(f"{image}: missing label {label.name}")
                continue
            if not label.read_text(encoding="utf-8").strip():
                report.background_image_count += 1
                report.split_background_counts[split] += 1
            else:
                report.labelled_image_count += 1
            report.errors.extend(validate_label(label, report, split))
        if label_dir.exists():
            image_stems = {image.stem for image in image_dir.iterdir() if image.suffix.lower() in IMAGE_SUFFIXES}
            for label in label_dir.glob("*.txt"):
                if label.stem not in image_stems:
                    report.errors.append(f"{label}: label has no matching image")
    if report.image_count == 0:
        report.errors.append("dataset contains no images")
    for class_id in range(CLASS_COUNT):
        if not report.class_counts[class_id]:
            report.errors.append(f"class {class_id} has no labelled examples")
        elif report.class_counts[class_id] < 50:
            report.warnings.append(f"class {class_id} has fewer than 50 labelled instances")
        for split in SPLITS:
            if not report.split_class_counts[split][class_id]:
                report.errors.append(f"{split}: class {class_id} has no labelled examples")
    if report.split_background_counts["test"] < 50:
        report.warnings.append("test split has fewer than 50 labelled background/negative images")
    fingerprint = hashlib.sha256()
    for path in sorted(dataset_root.rglob("*")):
        if path.is_file() and (path.suffix.lower() in IMAGE_SUFFIXES or path.suffix.lower() == ".txt"):
            fingerprint.update(path.relative_to(dataset_root).as_posix().encode("utf-8"))
            fingerprint.update(_sha256(path).encode("ascii"))
    report.dataset_fingerprint_sha256 = fingerprint.hexdigest()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=Path("training/datasets/port"))
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    report = validate_dataset(args.dataset_root)
    if args.report:
        payload = asdict(report)
        payload["class_counts"] = dict(report.class_counts)
        payload["split_image_counts"] = dict(report.split_image_counts)
        payload["split_background_counts"] = dict(report.split_background_counts)
        payload["split_class_counts"] = {split: dict(counts) for split, counts in report.split_class_counts.items()}
        args.report.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if report.errors:
        print("PORT_DATASET=FAIL")
        print("\n".join(report.errors[:100]))
        raise SystemExit(1)
    print(f"PORT_DATASET=PASS images={report.image_count} classes={','.join(CLASS_NAMES)}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
