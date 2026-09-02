import hashlib
import json

from app.model_release import verify_model_release


def test_verified_model_release_requires_correct_hash_and_classes(tmp_path):
    model = tmp_path / "port-yolo.pt"
    model.write_bytes(b"approved-port-model")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "model_name": "port-yolo",
                "model_version": "1.0.0",
                "classes": ["small_boat", "cargo_vessel"],
                "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "dataset_version": "port-2026-08",
                "dataset_license": "operator-owned",
            }
        ),
        encoding="utf-8",
    )
    release = verify_model_release(
        str(model),
        str(manifest),
        required=True,
        expected_classes={"small_boat", "cargo_vessel"},
    )
    assert release.verified
    assert release.version == "1.0.0"
    assert release.sha256 == hashlib.sha256(model.read_bytes()).hexdigest()
