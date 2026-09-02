"""Verify then atomically promote an approved port model release locally."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from validate_port_dataset import CLASS_COUNT


def sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gate-report", type=Path, required=True,
                        help="Passing release-gate JSON produced from this exact candidate model")
    parser.add_argument("--evaluation-report", type=Path, required=True,
                        help="Held-out evaluation JSON produced from this exact candidate model and dataset")
    # The trainer mounts the persistent host models directory at /models.
    # Writing below /service would disappear when `docker compose run --rm`
    # removes the training container.
    parser.add_argument("--release-dir", type=Path, default=Path("/models/port"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    gate = json.loads(args.gate_report.read_text(encoding="utf-8"))
    evaluation = json.loads(args.evaluation_report.read_text(encoding="utf-8"))
    required = {"model_name", "model_version", "classes", "sha256", "dataset_version", "dataset_license",
                "dataset_card_path", "dataset_fingerprint_sha256"}
    if required.difference(manifest):
        raise SystemExit("Manifest is incomplete")
    if manifest["classes"] != ["small_boat", "cargo_vessel"] or len(manifest["classes"]) != CLASS_COUNT:
        raise SystemExit("Manifest classes do not match the approved port-model contract")
    if sha256_file(args.model).lower() != str(manifest["sha256"]).lower():
        raise SystemExit("Candidate model SHA-256 does not match manifest")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(manifest["dataset_fingerprint_sha256"])):
        raise SystemExit("Manifest dataset_fingerprint_sha256 is not a SHA-256 value")
    dataset_card = Path(str(manifest["dataset_card_path"]))
    if not dataset_card.is_file():
        raise SystemExit("Manifest dataset card does not exist locally")
    if evaluation.get("schema") != "sentinel-port-evaluation/1":
        raise SystemExit("Evaluation report has an unexpected schema")
    if str(evaluation.get("model_sha256", "")).lower() != str(manifest["sha256"]).lower():
        raise SystemExit("Evaluation report does not belong to this exact candidate model")
    if str(evaluation.get("dataset_fingerprint_sha256", "")).lower() != str(manifest["dataset_fingerprint_sha256"]).lower():
        raise SystemExit("Evaluation report does not belong to the manifest dataset fingerprint")
    if gate.get("schema") != "sentinel-port-release-gate/1" or gate.get("passed") is not True:
        raise SystemExit("Candidate model did not pass the deterministic release gate")
    if str(gate.get("model_sha256", "")).lower() != str(manifest["sha256"]).lower():
        raise SystemExit("Release gate report does not belong to this exact candidate model")
    args.release_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.release_dir) as temporary:
        temporary_dir = Path(temporary)
        staged_model = temporary_dir / "port-yolo.pt"
        staged_manifest = temporary_dir / "manifest.json"
        shutil.copy2(args.model, staged_model)
        shutil.copy2(args.manifest, staged_manifest)
        os.replace(staged_model, args.release_dir / "port-yolo.pt")
        os.replace(staged_manifest, args.release_dir / "manifest.json")
    print("PORT_MODEL_PROMOTION=PASS")
