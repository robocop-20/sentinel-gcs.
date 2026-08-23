"""Bounded local storage of optional YOLO object crops.

This module has no face handling: callers give it an object bounding box from
YOLO. It is disabled by default so the normal perception path persists no
camera imagery. One current crop per persistent track bounds disk growth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from pathlib import Path
from uuid import uuid4

import cv2

from .evidence_crypto import encrypt_evidence, load_evidence_key
from .schemas import EvidenceArtifact

LOGGER = logging.getLogger(__name__)


class EvidenceStore:
    def __init__(
        self,
        *,
        enabled: bool,
        directory: str,
        interval_s: float,
        max_dimension_px: int,
        jpeg_quality: int,
        encryption_key_file: str,
    ) -> None:
        self.enabled = enabled
        self.directory = Path(directory)
        self.interval_s = max(interval_s, 0)
        self.max_dimension_px = max(max_dimension_px, 32)
        self.jpeg_quality = min(max(jpeg_quality, 1), 100)
        self._key = load_evidence_key(encryption_key_file) if enabled else b""
        self._last_saved: dict[str, float] = {}

    @staticmethod
    def _safe_name(track_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", track_id)

    def store(
        self,
        track_id: str,
        frame,
        xyxy: tuple[float, float, float, float],
        captured_at: float,
    ) -> EvidenceArtifact | None:
        """Save a padded object crop atomically and return its container path.

        A failure to save evidence must never interrupt live inference.
        """
        if not self.enabled or frame is None:
            return None
        if captured_at - self._last_saved.get(track_id, 0) < self.interval_s:
            return None
        evidence_id = str(uuid4())
        output = self.directory / (
            f"{self._safe_name(track_id)}-{int(captured_at * 1000)}-{evidence_id}.jpg.enc"
        )
        manifest_path = output.with_suffix(output.suffix + ".manifest.json")
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = xyxy
        margin_x, margin_y = (x2 - x1) * 0.08, (y2 - y1) * 0.08
        left, top = max(0, int(x1 - margin_x)), max(0, int(y1 - margin_y))
        right, bottom = min(width, int(x2 + margin_x)), min(height, int(y2 + margin_y))
        if right <= left or bottom <= top:
            return None
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return None
        scale = min(1.0, self.max_dimension_px / max(crop.shape[:2]))
        if scale < 1.0:
            crop = cv2.resize(
                crop,
                (
                    max(1, round(crop.shape[1] * scale)),
                    max(1, round(crop.shape[0] * scale)),
                ),
                interpolation=cv2.INTER_AREA,
            )
        temporary = output.with_name(f".{output.name}.tmp")
        temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            ok, encoded = cv2.imencode(
                ".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            if not ok:
                return None
            envelope = encrypt_evidence(encoded.tobytes(), output.name, self._key)
            digest = hashlib.sha256(envelope).hexdigest()
            temporary.write_bytes(envelope)
            os.replace(temporary, output)
            manifest = {
                "schema": "sentinel-evidence-manifest/v1",
                "evidence_id": evidence_id,
                "track_id": track_id,
                "created_at": captured_at,
                "artifact_name": output.name,
                "artifact_sha256": digest,
                "artifact_size_bytes": len(envelope),
                "encryption_format": "AES-256-GCM/SNTLENC1",
            }
            canonical = json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
            manifest_hmac = hmac.new(self._key, canonical, hashlib.sha256).hexdigest()
            temporary_manifest.write_text(
                json.dumps(
                    {**manifest, "manifest_hmac_sha256": manifest_hmac},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            os.replace(temporary_manifest, manifest_path)
            self._last_saved[track_id] = captured_at
            return EvidenceArtifact(
                evidence_id=evidence_id,
                path=str(output),
                sha256=digest,
                size_bytes=len(envelope),
                created_at=captured_at,
                manifest_path=str(manifest_path),
                manifest_hmac_sha256=manifest_hmac,
            )
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
                temporary_manifest.unlink(missing_ok=True)
                output.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning(
                    "Incomplete evidence cleanup failed",
                    extra={"event": "evidence_cleanup_failed"},
                    exc_info=True,
                )
            return None
