"""Controlled YOLO11 fine-tuning entry point for the local port dataset."""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from validate_port_dataset import validate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune YOLO11 on the validated port dataset.")
    parser.add_argument("--data", type=Path, default=Path("training/port.yaml"))
    parser.add_argument("--base-model", default="yolo11s.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", type=int, default=2, help="Safe starting batch for the available 4 GB GPU")
    parser.add_argument("--device", default="0", help="GPU index, or cpu for a slow validation run")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Data-loader workers; 0 avoids Docker shared-memory exhaustion on the local training host.",
    )
    parser.add_argument("--project", type=Path, default=Path("training/runs"))
    parser.add_argument("--name", default="port-yolo11")
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Use only when the caller has already validated the unchanged dataset.",
    )
    parser.add_argument(
        "--stage-dataset",
        action="store_true",
        help="Copy the dataset into the trainer temporary filesystem before fitting.",
    )
    args = parser.parse_args()

    if not args.skip_validation:
        report = validate_dataset(Path("training/datasets/port"))
        if report.errors:
            raise SystemExit("Refusing to train: run validate_port_dataset.py and correct dataset errors first")

    staged_root: Path | None = None
    data_path = args.data
    if args.stage_dataset:
        source_dataset = Path("training/datasets/port")
        staged_root = Path(tempfile.mkdtemp(prefix="sentinel-port-"))
        staged_dataset = staged_root / "dataset"
        print(f"Staging dataset locally at {staged_dataset} before training...")
        shutil.copytree(source_dataset, staged_dataset)
        data_path = staged_root / "port.yaml"
        data_path.write_text(
            "\n".join(
                (
                    f"path: {staged_dataset}",
                    "train: images/train",
                    "val: images/val",
                    "test: images/test",
                    "names:",
                    "  0: small_boat",
                    "  1: cargo_vessel",
                    "",
                )
            ),
            encoding="utf-8",
        )

    try:
        from ultralytics import YOLO

        model = YOLO(args.base_model)
        model.train(
            data=str(data_path), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
            device=args.device, workers=args.workers, project=str(args.project), name=args.name,
            pretrained=True, exist_ok=True, patience=20, save=True, plots=True, seed=42,
            deterministic=True,
        )
    finally:
        if staged_root is not None:
            shutil.rmtree(staged_root, ignore_errors=True)


if __name__ == "__main__":
    main()
