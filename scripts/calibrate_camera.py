"""Create a versioned Sentinel intrinsic-calibration profile from checkerboards."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from app.calibration import payload_sha256


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as temporary:
        json.dump(payload, temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--images", required=True, help="Image glob, for example calibration/*.jpg"
    )
    parser.add_argument("--columns", type=int, required=True, help="Inner checkerboard columns")
    parser.add_argument("--rows", type=int, required=True, help="Inner checkerboard rows")
    parser.add_argument("--square-size-m", type=float, required=True)
    parser.add_argument("--minimum-views", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.columns < 3 or args.rows < 3 or args.square_size_m <= 0:
        raise SystemExit("Checkerboard dimensions and square size must be positive")
    image_paths = sorted(Path(item) for item in glob.glob(args.images))
    if len(image_paths) < args.minimum_views:
        raise SystemExit(
            f"Need at least {args.minimum_views} calibration images; found {len(image_paths)}"
        )

    object_template = np.zeros((args.rows * args.columns, 3), np.float32)
    object_template[:, :2] = np.mgrid[0 : args.columns, 0 : args.rows].T.reshape(-1, 2)
    object_template *= args.square_size_m
    object_points: list[np.ndarray] = []
    image_points: list[np.ndarray] = []
    accepted: list[Path] = []
    image_size: tuple[int, int] | None = None
    for image_path in image_paths:
        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        current_size = (image.shape[1], image.shape[0])
        if image_size is None:
            image_size = current_size
        if current_size != image_size:
            raise SystemExit("All calibration images must use the same resolution")
        found, corners = cv2.findChessboardCornersSB(
            image,
            (args.columns, args.rows),
            flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY,
        )
        if found:
            object_points.append(object_template.copy())
            image_points.append(corners)
            accepted.append(image_path)
    if len(accepted) < args.minimum_views or image_size is None:
        raise SystemExit(
            f"Checkerboard found in {len(accepted)} views; need {args.minimum_views}"
        )

    rms, matrix, distortion, rotations, translations = cv2.calibrateCamera(
        object_points, image_points, image_size, None, None
    )
    per_view_errors: list[float] = []
    for object_set, image_set, rotation, translation in zip(
        object_points, image_points, rotations, translations
    ):
        projected, _ = cv2.projectPoints(
            object_set, rotation, translation, matrix, distortion
        )
        error = cv2.norm(image_set, projected, cv2.NORM_L2) / len(projected)
        per_view_errors.append(float(error))
    payload = {
        "schema": "sentinel-camera-intrinsics/1",
        "camera_id": args.camera_id,
        "version": args.version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkerboard": {
            "columns": args.columns,
            "rows": args.rows,
            "square_size_m": args.square_size_m,
        },
        "image_size": list(image_size),
        "accepted_view_count": len(accepted),
        "intrinsic_matrix": matrix.tolist(),
        "distortion_coefficients": distortion.reshape(-1).tolist(),
        "rms_reprojection_error_px": float(rms),
        "per_view_errors_px": per_view_errors,
        "source_images": [
            {"name": path.name, "sha256": file_sha256(path)} for path in accepted
        ],
    }
    payload["payload_sha256"] = payload_sha256(payload)
    write_atomic(args.output, payload)
    print(
        f"CALIBRATION_PROFILE=CREATED views={len(accepted)} rms_px={rms:.6f} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
