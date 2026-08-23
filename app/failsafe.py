"""Read-only per-layer fail-safe assessment for operators and monitoring."""

from __future__ import annotations

import time
from typing import Any

from .config import Settings
from .state import OperationsState


def _layer(
    layer_id: str,
    component: str,
    status: str,
    reason: str,
    safe_response: str,
    *,
    critical: bool = False,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": layer_id,
        "component": component,
        "status": status,
        "critical": critical,
        "reason": reason,
        "safe_response": safe_response,
        "evidence": evidence or {},
    }


def assess_fail_safe(
    settings: Settings,
    state: OperationsState,
    pipeline_health: dict,
    *,
    mqtt_connected: bool,
    storage_available: bool,
    llm_health: dict,
    security_llm_health: dict,
    security_health: dict | None = None,
) -> dict[str, Any]:
    """Describe failure containment without issuing restart or device commands."""
    now = time.time()
    latest = max(
        state.vision_metrics.values(), key=lambda item: item.timestamp, default=None
    )
    metric_age = max(0.0, now - latest.timestamp) if latest else None
    fresh = bool(
        latest
        and metric_age is not None
        and metric_age <= settings.vision_metrics_stale_s
    )
    processing = bool(fresh and latest and latest.status == "processing")
    workers = pipeline_health.get("workers", {})
    queues = pipeline_health.get("queues", {})
    queue_limits = {
        "ingress": settings.pipeline_queue_size,
        "rules": settings.pipeline_queue_size,
        "storage": settings.pipeline_queue_size,
        "egress": settings.pipeline_queue_size * 2,
    }
    max_queue_ratio = max(
        (
            float(queues.get(name, 0)) / max(limit, 1)
            for name, limit in queue_limits.items()
        ),
        default=0.0,
    )

    layers: list[dict[str, Any]] = []
    if latest is None:
        layers.append(
            _layer(
                "video",
                "OpenCV capture",
                "waiting",
                "No vision metrics received.",
                "Do not declare visual coverage; keep rules and storage available.",
                critical=True,
            )
        )
    elif not fresh:
        layers.append(
            _layer(
                "video",
                "OpenCV capture",
                "failed",
                "Vision heartbeat is stale.",
                "Mark camera coverage unavailable and let capture reconnect in isolation.",
                critical=True,
                evidence={
                    "metrics_age_s": round(metric_age or 0, 3),
                    "maximum_age_s": settings.vision_metrics_stale_s,
                },
            )
        )
    elif latest.status != "processing":
        layers.append(
            _layer(
                "video",
                "OpenCV capture",
                "degraded",
                latest.last_error or latest.status,
                "Suppress camera-ready claims while the capture worker reconnects.",
                critical=True,
                evidence={"capture_fps": latest.capture_fps, "status": latest.status},
            )
        )
    else:
        layers.append(
            _layer(
                "video",
                "OpenCV capture",
                "healthy",
                "Fresh frames are being processed.",
                "Continue latest-frame processing; discard stale buffered frames.",
                critical=True,
                evidence={
                    "capture_fps": latest.capture_fps,
                    "metrics_age_s": round(metric_age or 0, 3),
                },
            )
        )

    if not processing:
        detection_status, detection_reason = (
            "failed",
            "Detection has no fresh processing frames.",
        )
    elif latest and latest.last_error:
        detection_status, detection_reason = "degraded", latest.last_error
    elif latest and latest.inference_fps < settings.field_min_inference_fps:
        detection_status, detection_reason = (
            "degraded",
            "Inference throughput is below the configured field target.",
        )
    elif (
        latest
        and settings.require_model_manifest
        and not latest.model_integrity_verified
    ):
        detection_status, detection_reason = (
            "failed",
            "Required model integrity verification did not pass.",
        )
    else:
        detection_status, detection_reason = (
            "healthy",
            "Local YOLO inference is current.",
        )
    layers.append(
        _layer(
            "detection",
            "YOLO11 perception",
            detection_status,
            detection_reason,
            "Never substitute an LLM result for a missing local detection.",
            critical=True,
            evidence={
                "inference_fps": latest.inference_fps if latest else None,
                "model_integrity_verified": latest.model_integrity_verified
                if latest
                else False,
                "rejected_low_confidence": (
                    latest.detections_rejected_low_confidence if latest else 0
                ),
                "rejected_temporal_or_unstable": (
                    latest.detections_rejected_temporal if latest else 0
                ),
                "rejected_person_crosscheck": (
                    latest.detections_rejected_person_verifier if latest else 0
                ),
            },
        )
    )

    tracking_status = "healthy" if processing else "failed"
    layers.append(
        _layer(
            "tracking",
            "ByteTrack anonymous tracking",
            tracking_status,
            "Tracker receives fresh detections."
            if processing
            else "Tracker cannot be trusted without fresh detections.",
            "Expire stale tracks and publish only class-stable, strong multi-frame evidence.",
            critical=True,
            evidence={
                "minimum_observations": settings.min_track_confirmation_frames,
                "evidence_window": settings.track_evidence_window,
                "minimum_class_stability": settings.track_min_class_stability,
                "person_min_mean_confidence": settings.person_track_min_mean_confidence,
                "object_min_mean_confidence": settings.object_track_min_mean_confidence,
            },
        )
    )

    if not settings.enable_person_verifier:
        person_status, person_reason = (
            "disabled",
            "Independent local person cross-check is disabled.",
        )
    elif processing and latest and latest.person_verifier_loaded:
        person_status, person_reason = (
            "healthy",
            "Independent local person cross-check model is loaded.",
        )
    else:
        person_status, person_reason = (
            "degraded",
            "Person cross-check is configured but not confirmed loaded.",
        )
    layers.append(
        _layer(
            "person_crosscheck",
            "Local marginal-person verifier",
            person_status,
            person_reason,
            "Preserve primary YOLO availability; reject only explicit local contradictions.",
        )
    )

    if not settings.enable_face_detection:
        face_status, face_reason = "disabled", "Local face observation is disabled."
    elif (
        processing
        and latest
        and latest.face_detector_loaded
        and not latest.face_last_error
    ):
        face_status, face_reason = (
            "healthy",
            "Local face detector is loaded and isolated.",
        )
    else:
        face_status, face_reason = (
            "degraded",
            (
                (latest.face_last_error if latest else None)
                or "Face detector is not confirmed loaded."
            ),
        )
    layers.append(
        _layer(
            "face_observation",
            "Local face observation and privacy blur",
            face_status,
            face_reason,
            "Disable face observations for the affected frame; keep object tracking active.",
        )
    )

    if not settings.enable_fall_detection:
        fall_status, fall_reason = (
            "disabled",
            "Optional local pose observation is disabled.",
        )
    elif (
        latest
        and latest.fall_pose_model_loaded
        and not latest.fall_last_error
        and fresh
    ):
        fall_status, fall_reason = (
            "healthy",
            "Pose model is loaded; fall decisions remain temporal and advisory.",
        )
    else:
        fall_status, fall_reason = (
            "degraded",
            (
                (latest.fall_last_error if latest else None)
                or "Pose model is not confirmed healthy."
            ),
        )
    layers.append(
        _layer(
            "fall_pose",
            "Local pose/fall observation",
            fall_status,
            fall_reason,
            "Do not emit a fall alert without sustained local pose evidence.",
        )
    )

    fusion_worker = bool(workers.get("fusion-layer"))
    rules_worker = bool(workers.get("rules-layer"))
    layers.append(
        _layer(
            "fusion",
            "GPS/IMU/LiDAR fusion",
            "healthy" if fusion_worker else "failed",
            "Fusion worker is alive."
            if fusion_worker
            else "Fusion worker is not alive.",
            "Keep detections unlocated when synchronized telemetry/range is unavailable.",
            critical=True,
            evidence={
                "telemetry_present": state.telemetry is not None,
                "range_present": state.range_measurement is not None,
            },
        )
    )
    telemetry_age = (
        max(0.0, now - state.telemetry.timestamp) if state.telemetry else None
    )
    telemetry_fresh = bool(
        telemetry_age is not None
        and telemetry_age <= settings.security_telemetry_stale_s
    )
    layers.append(
        _layer(
            "telemetry",
            "GPS/IMU/LiDAR telemetry",
            "healthy" if telemetry_fresh else "waiting",
            "Telemetry is fresh."
            if telemetry_fresh
            else "Fresh flight-controller telemetry is unavailable.",
            "Do not geolocate or decide geofence entry using stale/missing telemetry.",
            evidence={
                "age_s": telemetry_age,
                "maximum_age_s": settings.security_telemetry_stale_s,
            },
        )
    )
    geo_ready = bool(
        state.telemetry
        and (
            not settings.enable_ray_plane_geolocation
            or (settings.camera_fx_px > 0 and settings.camera_fy_px > 0)
        )
    )
    layers.append(
        _layer(
            "geolocation",
            "Detection geolocation",
            "healthy" if geo_ready else "waiting",
            "Synchronized telemetry and configured geometry are available."
            if geo_ready
            else "Awaiting telemetry and/or camera calibration.",
            "Do not infer restricted-zone entry from image coordinates alone.",
        )
    )

    rules_status = (
        "healthy"
        if rules_worker and max_queue_ratio < settings.failsafe_max_queue_ratio
        else "degraded"
    )
    layers.append(
        _layer(
            "rules",
            "Deterministic geofence/risk rules",
            rules_status,
            "Rules worker and queue headroom are available."
            if rules_status == "healthy"
            else "Rules worker stopped or queue pressure is high.",
            "Retain deterministic authority; shed advisory work before safety work.",
            critical=True,
            evidence={
                "max_queue_ratio": round(max_queue_ratio, 3),
                "errors": pipeline_health.get("errors", {}),
            },
        )
    )

    layers.append(
        _layer(
            "storage",
            "PostGIS persistence",
            "healthy" if storage_available else "degraded",
            "PostGIS is connected." if storage_available else "PostGIS is unavailable.",
            "Keep live processing active and retry writes through the isolated storage queue.",
        )
    )
    layers.append(
        _layer(
            "transport",
            "MQTT event transport",
            "healthy" if mqtt_connected else "degraded",
            "MQTT is connected." if mqtt_connected else "MQTT is unavailable.",
            "Keep local alerts active; queue only within bounded memory and report loss.",
        )
    )

    if not settings.enable_v2x:
        v2x_status, v2x_reason = "disabled", "V2X profile is not enabled."
    elif not settings.v2x_shared_secret or not mqtt_connected:
        v2x_status, v2x_reason = (
            "degraded",
            "Signed V2X transport prerequisites are unavailable.",
        )
    else:
        v2x_status, v2x_reason = (
            "healthy",
            "Signed V2X relay prerequisites are present.",
        )
    layers.append(
        _layer(
            "v2x",
            "Signed V2X event relay",
            v2x_status,
            v2x_reason,
            "Never issue device commands; reject unsigned, stale, or replayed envelopes.",
        )
    )

    integrity = security_health or {}
    if not integrity.get("enabled"):
        integrity_status, integrity_reason = (
            "disabled",
            "Deterministic integrity monitoring is disabled.",
        )
    elif mqtt_connected and not integrity.get("mqtt_tls_configured"):
        integrity_status, integrity_reason = (
            "degraded",
            "Integrity checks are active, but MQTT TLS is not configured.",
        )
    else:
        integrity_status, integrity_reason = (
            "healthy",
            "Deterministic telemetry/V2X integrity checks are active.",
        )
    layers.append(
        _layer(
            "security_integrity",
            "Telemetry/V2X integrity monitor",
            integrity_status,
            integrity_reason,
            "Keep findings advisory; reject invalid signed envelopes and require operator review.",
        )
    )

    for layer_id, label, health in (
        ("llm_object", "External object advisory", llm_health),
        ("llm_security", "External security advisory", security_llm_health),
    ):
        if not health.get("enabled"):
            llm_status, llm_reason = (
                "disabled",
                "Optional advisory provider is disabled.",
            )
        elif not health.get("worker"):
            llm_status, llm_reason = "degraded", "Advisory worker is not running."
        elif health.get("circuit", {}).get("state") in {"open", "half_open"}:
            llm_status, llm_reason = (
                "degraded",
                "Provider circuit breaker is limiting requests.",
            )
        else:
            llm_status, llm_reason = (
                "healthy",
                "Bounded asynchronous advisory worker is available.",
            )
        layers.append(
            _layer(
                layer_id,
                label,
                llm_status,
                llm_reason,
                "Continue deterministic local decisions; never block or override the core pipeline.",
                evidence={
                    "queued": health.get("queued", 0),
                    "dropped": health.get("dropped", 0),
                    "circuit": health.get("circuit", {}),
                },
            )
        )

    critical = [item for item in layers if item["critical"]]
    critical_healthy = all(item["status"] == "healthy" for item in critical)
    waiting = any(item["status"] == "waiting" for item in critical)
    return {
        "status": "operational"
        if critical_healthy
        else ("waiting" if waiting else "degraded"),
        "fail_safe_active": not critical_healthy,
        "critical_path_healthy": critical_healthy,
        "automatic_device_actions": False,
        "generated_at": now,
        "layers": layers,
        "note": "This is runtime failure containment, not certification or field acceptance.",
    }
