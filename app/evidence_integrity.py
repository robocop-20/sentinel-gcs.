"""Offline verification of encrypted evidence artifacts and signed manifests."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any


def verify_evidence_files(
    artifact_path: str, manifest_path: str, key: bytes
) -> dict[str, Any]:
    artifact = Path(artifact_path)
    manifest_file = Path(manifest_path)
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        expected_hmac = str(manifest.pop("manifest_hmac_sha256"))
        canonical = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        actual_hmac = hmac.new(key, canonical, hashlib.sha256).hexdigest()
        actual_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        valid = hmac.compare_digest(expected_hmac, actual_hmac) and hmac.compare_digest(
            str(manifest.get("artifact_sha256", "")), actual_hash
        )
        return {
            "valid": valid,
            "artifact_sha256": actual_hash,
            "manifest_hmac_valid": hmac.compare_digest(expected_hmac, actual_hmac),
            "artifact_hash_valid": hmac.compare_digest(
                str(manifest.get("artifact_sha256", "")), actual_hash
            ),
            "evidence_id": manifest.get("evidence_id"),
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"valid": False, "error": type(exc).__name__}
