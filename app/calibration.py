"""Versioned camera calibration and extrinsics profile validation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def payload_sha256(payload: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "payload_sha256"}
    canonical = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_profile(path: str, expected_kind: str, camera_id: str) -> dict[str, Any]:
    profile_path = Path(path)
    if not profile_path.is_file():
        raise ValueError(f"{expected_kind} profile does not exist: {profile_path}")
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {expected_kind} profile: {profile_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != expected_kind:
        raise ValueError(f"Profile schema must be {expected_kind}")
    if payload.get("camera_id") != camera_id:
        raise ValueError(
            f"Profile camera_id {payload.get('camera_id')!r} does not match {camera_id!r}"
        )
    claimed_hash = str(payload.get("payload_sha256", ""))
    if len(claimed_hash) != 64 or claimed_hash != payload_sha256(payload):
        raise ValueError(f"{expected_kind} profile checksum failed")
    return payload


@dataclass(frozen=True)
class IntrinsicCalibration:
    camera_id: str
    version: str
    fx_px: float
    fy_px: float
    cx_px: float
    cy_px: float
    distortion: tuple[float, ...]
    image_width: int
    image_height: int
    rms_reprojection_error_px: float
    sha256: str


@dataclass(frozen=True)
class CameraExtrinsics:
    camera_id: str
    version: str
    rotation: tuple[float, ...]
    translation_m: tuple[float, float, float]
    sha256: str


def validate_rotation_matrix(rotation: tuple[float, ...], tolerance: float = 0.01) -> None:
    if len(rotation) != 9 or not all(math.isfinite(value) for value in rotation):
        raise ValueError("Camera rotation must contain nine finite values")
    rows = [rotation[index : index + 3] for index in (0, 3, 6)]
    for index, row in enumerate(rows):
        norm = math.sqrt(sum(value * value for value in row))
        if abs(norm - 1) > tolerance:
            raise ValueError(f"Camera rotation row {index} is not unit length")
    for first in range(3):
        for second in range(first + 1, 3):
            dot = sum(rows[first][index] * rows[second][index] for index in range(3))
            if abs(dot) > tolerance:
                raise ValueError("Camera rotation rows are not orthogonal")
    determinant = (
        rotation[0] * (rotation[4] * rotation[8] - rotation[5] * rotation[7])
        - rotation[1] * (rotation[3] * rotation[8] - rotation[5] * rotation[6])
        + rotation[2] * (rotation[3] * rotation[7] - rotation[4] * rotation[6])
    )
    if abs(determinant - 1) > tolerance:
        raise ValueError("Camera rotation determinant must be approximately +1")


def load_intrinsic_calibration(path: str, camera_id: str) -> IntrinsicCalibration:
    payload = _load_profile(path, "sentinel-camera-intrinsics/1", camera_id)
    matrix = payload.get("intrinsic_matrix")
    distortion = payload.get("distortion_coefficients")
    image_size = payload.get("image_size")
    if (
        not isinstance(matrix, list)
        or len(matrix) != 3
        or any(not isinstance(row, list) or len(row) != 3 for row in matrix)
    ):
        raise ValueError("intrinsic_matrix must be a 3x3 array")
    if not isinstance(distortion, list) or len(distortion) < 4:
        raise ValueError("distortion_coefficients must contain at least four values")
    if not isinstance(image_size, list) or len(image_size) != 2:
        raise ValueError("image_size must contain width and height")
    fx, fy = float(matrix[0][0]), float(matrix[1][1])
    cx, cy = float(matrix[0][2]), float(matrix[1][2])
    width, height = int(image_size[0]), int(image_size[1])
    rms = float(payload.get("rms_reprojection_error_px", -1))
    if fx <= 0 or fy <= 0 or width <= 0 or height <= 0 or rms < 0:
        raise ValueError("Intrinsic calibration contains invalid numeric values")
    return IntrinsicCalibration(
        camera_id=camera_id,
        version=str(payload.get("version", "")),
        fx_px=fx,
        fy_px=fy,
        cx_px=cx,
        cy_px=cy,
        distortion=tuple(float(value) for value in distortion),
        image_width=width,
        image_height=height,
        rms_reprojection_error_px=rms,
        sha256=str(payload["payload_sha256"]),
    )


def load_camera_extrinsics(path: str, camera_id: str) -> CameraExtrinsics:
    payload = _load_profile(path, "sentinel-camera-extrinsics/1", camera_id)
    rotation = tuple(float(value) for value in payload.get("rotation_matrix", []))
    validate_rotation_matrix(rotation)
    translation = tuple(float(value) for value in payload.get("translation_m", []))
    if len(translation) != 3 or not all(math.isfinite(value) for value in translation):
        raise ValueError("translation_m must contain three finite values")
    return CameraExtrinsics(
        camera_id=camera_id,
        version=str(payload.get("version", "")),
        rotation=rotation,
        translation_m=(translation[0], translation[1], translation[2]),
        sha256=str(payload["payload_sha256"]),
    )
