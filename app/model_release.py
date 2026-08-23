"""Verified model-release metadata for controlled perception deployments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelRelease:
    model_path: str
    release_name: str
    version: str
    verified: bool
    classes: tuple[str, ...]
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_release(
    model_path: str, manifest_path: str, *, required: bool, expected_classes: set[str]
) -> ModelRelease:
    model = Path(model_path)
    if not model.is_file():
        raise ValueError(f"YOLO_MODEL does not exist: {model_path}")
    if not manifest_path:
        if required:
            raise ValueError(
                "MODEL_MANIFEST_PATH is required for this production model release"
            )
        return ModelRelease(
            str(model), model.name, "unmanaged", False, tuple(), sha256_file(model)
        )

    manifest_file = Path(manifest_path)
    if not manifest_file.is_file():
        raise ValueError(f"MODEL_MANIFEST_PATH does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("MODEL_MANIFEST_PATH is not valid JSON") from exc
    for key in (
        "model_name",
        "model_version",
        "classes",
        "sha256",
        "dataset_version",
        "dataset_license",
    ):
        if not manifest.get(key):
            raise ValueError(f"Model manifest is missing required field: {key}")
    classes = tuple(str(value).strip().lower() for value in manifest["classes"])
    if len(classes) != len(set(classes)):
        raise ValueError("Model manifest classes must be unique")
    missing = expected_classes.difference(classes)
    if missing:
        raise ValueError(
            f"Model manifest does not cover configured classes: {sorted(missing)}"
        )
    actual_hash = sha256_file(model)
    if actual_hash.lower() != str(manifest["sha256"]).lower():
        raise ValueError("Model SHA-256 does not match its manifest")
    return ModelRelease(
        str(model),
        str(manifest["model_name"]),
        str(manifest["model_version"]),
        True,
        classes,
        actual_hash,
    )
