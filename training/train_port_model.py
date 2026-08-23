"""Controlled YOLO11 fine-tuning entry point for the local port dataset."""
from __future__ import annotations

import argparse
from pathlib import Path
from validate_port_dataset import validate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune YOLO11 on the validated port dataset.")
    parser.add_argument("--data", type=Path, default=Path("training/port.yaml"))
    parser.add_argument("--base-model", default="yolo11s.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", type=int, default=4, help="Safe starting batch for the available 4 GB GPU")
    parser.add_argument("--device", default="0", help="GPU index, or cpu for a slow validation run")
    parser.add_argument("--project", type=Path, default=Path("training/runs"))
    parser.add_argument("--name", default="port-yolo11")
    args = parser.parse_args()

    report = validate_dataset(Path("training/datasets/port"))
    if report.errors:
        raise SystemExit("Refusing to train: run validate_port_dataset.py and correct dataset errors first")

    from ultralytics import YOLO
    model = YOLO(args.base_model)
    model.train(
        data=str(args.data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        device=args.device, project=str(args.project), name=args.name, pretrained=True,
        patience=20, save=True, plots=True, seed=42, deterministic=True,
    )


if __name__ == "__main__":
    main()
