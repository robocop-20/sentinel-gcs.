import json

import pytest

from app.calibration import (
    load_camera_extrinsics,
    load_intrinsic_calibration,
    payload_sha256,
)


def write_profile(path, payload):
    payload["payload_sha256"] = payload_sha256(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_intrinsic_profile_is_bound_to_camera_and_checksum(tmp_path):
    path = tmp_path / "intrinsics.json"
    payload = {
        "schema": "sentinel-camera-intrinsics/1",
        "camera_id": "camera-01",
        "version": "bench-1",
        "image_size": [1920, 1080],
        "intrinsic_matrix": [[1000, 0, 960], [0, 1001, 540], [0, 0, 1]],
        "distortion_coefficients": [0, 0, 0, 0, 0],
        "rms_reprojection_error_px": 0.2,
    }
    write_profile(path, payload)
    calibration = load_intrinsic_calibration(str(path), "camera-01")
    assert calibration.fx_px == 1000
    with pytest.raises(ValueError, match="does not match"):
        load_intrinsic_calibration(str(path), "camera-02")
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["intrinsic_matrix"][0][0] = 2000
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_intrinsic_calibration(str(path), "camera-01")


def test_extrinsics_profile_rejects_non_rotation_matrix(tmp_path):
    path = tmp_path / "extrinsics.json"
    payload = {
        "schema": "sentinel-camera-extrinsics/1",
        "camera_id": "camera-01",
        "version": "bench-1",
        "rotation_matrix": [1, 0, 0, 0, 1, 0, 0, 0, 2],
        "translation_m": [0, 0, 0],
    }
    write_profile(path, payload)
    with pytest.raises(ValueError, match="unit length"):
        load_camera_extrinsics(str(path), "camera-01")
