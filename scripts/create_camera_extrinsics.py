"""Create a checksummed camera-to-airframe extrinsics profile."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.calibration import payload_sha256, validate_rotation_matrix


def comma_floats(value: str, count: int, label: str) -> tuple[float, ...]:
    try:
        values = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must contain numeric values") from exc
    if len(values) != count:
        raise argparse.ArgumentTypeError(f"{label} must contain {count} values")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--rotation", required=True, help="Nine row-major values")
    parser.add_argument("--translation-m", default="0,0,0", help="x,y,z metres")
    parser.add_argument("--boresight-note", default="")
    parser.add_argument("--gimbal-frame", default="fixed")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rotation = comma_floats(args.rotation, 9, "rotation")
    translation = comma_floats(args.translation_m, 3, "translation")
    validate_rotation_matrix(rotation)
    payload = {
        "schema": "sentinel-camera-extrinsics/1",
        "camera_id": args.camera_id,
        "version": args.version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rotation_matrix": list(rotation),
        "translation_m": list(translation),
        "boresight_note": args.boresight_note,
        "gimbal_frame": args.gimbal_frame,
    }
    payload["payload_sha256"] = payload_sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=args.output.parent, delete=False
    ) as temporary:
        json.dump(payload, temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, args.output)
    print(f"EXTRINSICS_PROFILE=CREATED output={args.output}")


if __name__ == "__main__":
    main()
