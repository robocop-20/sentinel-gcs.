"""Advisory evidence orchestration for optional LLM/camera review.

This module deliberately does not call an LLM, alter risk scores, or issue an
alert. It emits a bounded request that an approved external verifier or camera
gateway may fulfil later.
"""

from __future__ import annotations

import time
from uuid import uuid4

from .config import Settings
from .schemas import EvidenceRequest, Event, Location, Telemetry


def _requested_camera_ids(
    settings: Settings, source_camera_id: str | None
) -> list[str]:
    cameras = [
        camera.strip()
        for camera in settings.evidence_camera_ids.split(",")
        if camera.strip()
    ]
    return [camera for camera in cameras if camera != source_camera_id]


def create_evidence_request(
    settings: Settings, event: Event, track: dict | None, telemetry: Telemetry | None
) -> EvidenceRequest | None:
    """Create review work only for local, high-risk events when explicitly enabled."""
    if not settings.enable_llm_verification or event.origin != "local" or track is None:
        return None
    if str(track.get("class", "")).lower() not in settings.llm_advisory_classes:
        return None
    if event.risk_score < settings.llm_verification_min_risk:
        return None
    source_camera_id = track.get("source") if track else None
    requested_at = time.time()
    reason = (
        f"Advisory visual verification requested for {event.event_type}; "
        f"risk={event.risk_score}; factors={','.join(event.risk_factors)}"
    )
    return EvidenceRequest(
        request_id=str(uuid4()),
        event_id=event.id,
        track_id=event.track_id,
        requested_at=requested_at,
        expires_at=requested_at + settings.evidence_request_ttl_s,
        reason=reason,
        source_camera_id=source_camera_id,
        requested_camera_ids=_requested_camera_ids(settings, source_camera_id),
        object_type=track.get("class") if track else None,
        detection_confidence=track.get("confidence") if track else None,
        evidence_ref=track.get("evidence_ref") if track else None,
        location=event.location,
    )


def create_detection_advisory_request(
    settings: Settings, track: dict
) -> EvidenceRequest | None:
    """Create a bounded non-person second-opinion request for one stable track.

    This path deliberately requires an already-confirmed local detection and a
    local object crop.  It is never used for people, face imagery, identity
    matching, model training, risk scoring, or alert decisions.
    """
    object_type = str(track.get("class", "")).lower()
    confidence = track.get("confidence")
    if (
        not settings.enable_llm_verification
        or not settings.enable_llm_detection_advisory
        or object_type not in settings.llm_advisory_classes
        or not isinstance(confidence, (int, float))
        or confidence < settings.llm_advisory_min_confidence
        or not track.get("evidence_ref")
        or not track.get("track_id")
    ):
        return None
    requested_at = time.time()
    track_id = str(track["track_id"])
    return EvidenceRequest(
        request_id=str(uuid4()),
        event_id=f"advisory:{track_id}:{int(requested_at)}",
        track_id=track_id,
        requested_at=requested_at,
        expires_at=requested_at + settings.evidence_request_ttl_s,
        reason=(
            "Advisory second opinion for a confirmed local YOLO object; "
            f"object={object_type}; confidence={confidence:.3f}"
        ),
        source_camera_id=track.get("source"),
        object_type=object_type,
        detection_confidence=float(confidence),
        evidence_ref=track.get("evidence_ref"),
        location=Location.model_validate(track["location"])
        if track.get("location")
        else None,
    )
