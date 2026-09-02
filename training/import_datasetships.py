#!/usr/bin/env python3
"""Import a DatasetShips YOLO export into Sentinel's two-class vessel dataset.

DatasetShips is CC BY 4.0. This maps TRAWLER/YACHT to ``small_boat`` and
BULK CARRIER/CONTAINER SHIP/GENERAL CARGO to ``cargo_vessel``. Remaining
source classes become background so the model does not label every vessel as a
target class.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import sys
from collections import Counter
from pathlib import Path


TARGET_NAMES = ("small_boat", "cargo_vessel")
CLASS_MAP = {
    "TRAWLER": 0,
    "YACHT": 0,
    "BULK CARRIER": 1,
    "CONTAINER SHIP": 1,
    "GENERAL CARGO": 1,
}
SPLIT_MAP = {"train": "train", "valid": "val", "val": "val", "test": "test"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def normalise_class_name(value: str) -> str:
    return " ".join(value.strip().strip("'\"").upper().split())


def read_class_names(data_yaml: Path) -> list[str]:
    """Read standard Roboflow/YOLO ``names`` formats without another dependency."""
    text = data_yaml.read_text(encoding="utf-8")
    inline = re.search(r"^names:\s*(\[[^\n]+\])\s*$", text, flags=re.MULTILINE)
    if inline:
        values = ast.literal_eval(inline.group(1))
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("`names` must be a list of class names")
        return values

    names: dict[int, str] = {}
    reading_names = False
    for line in text.splitlines():
        if re.match(r"^names:\s*$", line):
            reading_names = True
            continue
        if reading_names and line and not line[0].isspace():
            break
        if not reading_names:
            continue
        numbered = re.match(r"^\s*(\d+)\s*:\s*(.+?)\s*$", line)
        listed = re.match(r"^\s*-\s*(.+?)\s*$", line)
        if numbered:
            names[int(numbered.group(1))] = numbered.group(2).strip().strip("'\"")
        elif listed:
            names[len(names)] = listed.group(1).strip().strip("'\"")

    if not names:
        raise ValueError(f"Could not read class names from {data_yaml}")
    expected_ids = list(range(len(names)))
    if sorted(names) != expected_ids:
        raise ValueError("Source class identifiers must be consecutive and start at 0")
    return [names[index] for index in expected_ids]


def find_source_split(source: Path, split: str) -> tuple[Path, Path] | None:
    images = source / split / "images"
    labels = source / split / "labels"
    return (images, labels) if images.is_dir() and labels.is_dir() else None


def target_is_empty(target: Path) -> bool:
    return not any(path.is_file() for path in target.glob("images/*/*")) and not any(
        path.is_file() for path in target.glob("labels/*/*")
    )


def convert_labels(label_path: Path, source_names: list[str]) -> tuple[list[str], Counter[str]]:
    rows: list[str] = []
    mapped = Counter()
    for line_number, raw_line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = raw_line.split()
        if not fields:
            continue
        if len(fields) != 5:
            raise ValueError(f"{label_path}:{line_number} is not a YOLO bounding-box row")
        try:
            source_id = int(fields[0])
        except ValueError as error:
            raise ValueError(f"{label_path}:{line_number} has a non-integer class id") from error
        if source_id < 0 or source_id >= len(source_names):
            raise ValueError(f"{label_path}:{line_number} references unknown class id {source_id}")
        target_id = CLASS_MAP.get(normalise_class_name(source_names[source_id]))
        if target_id is not None:
            rows.append(" ".join([str(target_id), *fields[1:]]))
            mapped[TARGET_NAMES[target_id]] += 1
    return rows, mapped


def import_split(
    source_images: Path,
    source_labels: Path,
    target: Path,
    split: str,
    source_names: list[str],
    dry_run: bool,
) -> tuple[int, Counter[str], int]:
    image_target = target / "images" / split
    label_target = target / "labels" / split
    copied_images = 0
    mapped_boxes = Counter()
    background_images = 0
    for image_path in sorted(path for path in source_images.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES):
        label_path = source_labels / f"{image_path.stem}.txt"
        if not label_path.is_file():
            raise FileNotFoundError(f"Missing label for {image_path.name}: {label_path}")
        rows, counts = convert_labels(label_path, source_names)
        destination_stem = f"datasetships_{image_path.stem}"
        destination_image = image_target / f"{destination_stem}{image_path.suffix.lower()}"
        destination_label = label_target / f"{destination_stem}.txt"
        if destination_image.exists() or destination_label.exists():
            raise FileExistsError(f"Refusing to overwrite {destination_image.name}")
        if not dry_run:
            image_target.mkdir(parents=True, exist_ok=True)
            label_target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image_path, destination_image)
            destination_label.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
        copied_images += 1
        mapped_boxes.update(counts)
        background_images += not bool(rows)
    return copied_images, mapped_boxes, background_images


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Extracted DatasetShips YOLO11 export directory")
    parser.add_argument("--target", type=Path, default=Path("training/datasets/port"))
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without copying files")
    parser.add_argument("--append", action="store_true", help="Allow a non-empty target dataset")
    args = parser.parse_args()

    source = args.source.resolve()
    target = args.target.resolve()
    data_yaml = source / "data.yaml"
    if not data_yaml.is_file():
        raise FileNotFoundError(f"Expected source data.yaml at {data_yaml}")
    if not target_is_empty(target) and not args.append:
        raise RuntimeError(f"Target {target} already contains data; inspect it before using --append")
    source_names = read_class_names(data_yaml)
    unavailable = sorted(set(CLASS_MAP) - {normalise_class_name(name) for name in source_names})
    if unavailable:
        raise RuntimeError(f"Export is missing expected DatasetShips classes: {', '.join(unavailable)}")

    total_images, total_background, total_boxes = 0, 0, Counter()
    for source_split, target_split in SPLIT_MAP.items():
        located = find_source_split(source, source_split)
        if located is None:
            continue
        copied, boxes, background = import_split(*located, target, target_split, source_names, args.dry_run)
        print(f"{source_split} -> {target_split}: {copied} images, {background} target-background images")
        total_images += copied
        total_background += background
        total_boxes.update(boxes)
    if total_images == 0:
        raise RuntimeError("No train/valid/test image-and-label directories found")
    print(f"Images: {total_images}; background-only after mapping: {total_background}")
    for name in TARGET_NAMES:
        print(f"{name}: {total_boxes[name]} boxes")
    if any(total_boxes[name] == 0 for name in TARGET_NAMES):
        raise RuntimeError("A target class received zero boxes; do not train this dataset")
    print("Next: add licensed local port/drone data, validate, then train a candidate model. Never deploy automatically.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
