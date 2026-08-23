import hashlib
import hmac
import json

import pytest

from app.evidence_integrity import verify_evidence_files
from app.retention_worker import _inside


def test_signed_manifest_detects_artifact_tampering(tmp_path):
    key = b"k" * 32
    artifact = tmp_path / "object.jpg.enc"
    artifact.write_bytes(b"encrypted-envelope")
    manifest = {
        "schema": "sentinel-evidence-manifest/v1",
        "evidence_id": "evidence-1",
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    canonical = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    manifest_path = tmp_path / "object.jpg.enc.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                **manifest,
                "manifest_hmac_sha256": hmac.new(
                    key, canonical, hashlib.sha256
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    assert verify_evidence_files(str(artifact), str(manifest_path), key)["valid"]
    artifact.write_bytes(b"tampered")
    result = verify_evidence_files(str(artifact), str(manifest_path), key)
    assert not result["valid"]
    assert not result["artifact_hash_valid"]


def test_retention_rejects_paths_outside_evidence_root(tmp_path):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    assert _inside(evidence_root, str(evidence_root / "safe.enc")).parent == evidence_root
    with pytest.raises(ValueError, match="escaped"):
        _inside(evidence_root, str(tmp_path / "outside.enc"))
