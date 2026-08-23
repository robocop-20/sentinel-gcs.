from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field

UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class StrictBaseModel(BaseModel):
    """Reject fields outside the versioned API contract."""

    model_config = ConfigDict(extra="forbid")


class CameraSourceUpdate(StrictBaseModel):
    """Operator-selected primary HTTP(S) camera endpoint."""

    source: str = Field(min_length=3, max_length=512)


class DeviceEndpointRegistration(StrictBaseModel):
    """An operator registry entry; it does not grant V2X access or control."""

    device_id: str = Field(
        min_length=2, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]+$"
    )
    device_type: Literal["camera", "vehicle", "infrastructure", "drone"]
    endpoint: str = Field(min_length=3, max_length=512)


class BBox(StrictBaseModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class EvidenceArtifact(StrictBaseModel):
    """Immutable encrypted evidence metadata; it contains no image pixels."""

    evidence_id: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    created_at: float
    manifest_path: str
    manifest_hmac_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    encryption_format: Literal["AES-256-GCM/SNTLENC1"] = "AES-256-GCM/SNTLENC1"


class FallObservation(StrictBaseModel):
    """Local pose-and-time fall signal for an anonymous track, not identity data."""

    track_id: str
    timestamp: float
    confidence: float = Field(ge=0, le=1)
    torso_angle_deg: float = Field(ge=0, le=90)
    bbox_aspect_ratio: float = Field(ge=0)
    sustained_frames: int = Field(ge=1)
    advisory_only: Literal[True] = True


class Location(StrictBaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    approximate: bool = True
    method: Literal[
        "flat_ground_fov", "flat_ground_intrinsics", "ray_plane", "reported"
    ] = "flat_ground_fov"
    uncertainty_m: float | None = Field(default=None, ge=0)
    uncertainty_status: Literal["UNBOUNDED", "ESTIMATED", "VALIDATED"] = "UNBOUNDED"
    synchronization_delta_s: float | None = Field(default=None, ge=0)
    telemetry_timestamp: float | None = None
    range_timestamp: float | None = None


class Detection(StrictBaseModel):
    track_id: str
    class_name: str = Field(alias="class")
    confidence: float = Field(ge=0, le=1)
    bbox: BBox
    location: Location | None = None
    model_class: str | None = None
    # Smoothed display value for a persistent track. `confidence` remains raw.
    display_confidence: float | None = Field(default=None, ge=0, le=1)
    # Local-only path to an optional YOLO object crop. It is never a face crop
    # and is not sent in V2X payloads.
    evidence_ref: str | None = None
    evidence: EvidenceArtifact | None = None
    # Image-plane movement is not a world speed or geographic heading.
    motion: "Motion | None" = None
    confirmed_track_observations: int = Field(default=1, ge=1)
    track_mean_confidence: float | None = Field(default=None, ge=0, le=1)
    track_class_stability: float | None = Field(default=None, ge=0, le=1)
    # Optional local cross-model outcome for a marginal person box. This
    # carries no face data, biometric template, or identity information.
    person_verification: "PersonVerification | None" = None
    fall: FallObservation | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FaceDetection(StrictBaseModel):
    """Detection-only metadata. Never contains an embedding or identity."""

    confidence: float = Field(ge=0, le=1)
    bbox: BBox
    landmarks: list[tuple[float, float]] = Field(default_factory=list)
    linked_track_id: str | None = None
    # Short-lived spatial observation ID, not a biometric identifier.
    face_track_id: str | None = None
    quality: "FaceQuality | None" = None


class PersonVerification(StrictBaseModel):
    method: Literal["local_fasterrcnn_mobilenet"]
    verdict: Literal["confirmed", "contradicted", "unavailable"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    iou: float | None = Field(default=None, ge=0, le=1)


class Motion(StrictBaseModel):
    """Anonymous per-track image-plane movement metadata."""

    status: Literal["unknown", "stationary", "moving"]
    speed_image_px_s: float | None = Field(default=None, ge=0)
    image_heading_deg: float | None = Field(default=None, ge=0, lt=360)


class FaceQuality(StrictBaseModel):
    """Image-quality signals for operator review, not a biometric decision."""

    quality_score: float = Field(ge=0, le=1)
    usable_for_operator_review: bool
    sharpness_score: float = Field(ge=0, le=1)
    lighting_score: float = Field(ge=0, le=1)
    size_score: float = Field(ge=0, le=1)
    frontal_score: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)


class DetectionBatch(StrictBaseModel):
    batch_id: str | None = Field(default=None, min_length=16, max_length=128)
    timestamp: float
    captured_at: float | None = None
    source: str
    vehicle_id: str | None = Field(default=None, min_length=1, max_length=96)
    frame_width: int = Field(gt=0)
    frame_height: int = Field(gt=0)
    model_name: str | None = None
    model_version: str | None = None
    model_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    model_integrity_verified: bool = False
    inference_ms: float | None = Field(default=None, ge=0)
    detections: list[Detection]
    faces: list[FaceDetection] = Field(default_factory=list)


class VisionMetrics(StrictBaseModel):
    """Operational evidence for the live perception layer, not model accuracy claims."""

    source: str
    timestamp: float
    status: Literal["starting", "waiting_for_frames", "processing", "degraded"]
    model_name: str
    device: str
    frames_captured: int = Field(ge=0)
    frames_inferred: int = Field(ge=0)
    frames_posted: int = Field(ge=0)
    frames_dropped_for_latency: int = Field(ge=0)
    capture_fps: float = Field(ge=0)
    inference_fps: float = Field(ge=0)
    last_inference_ms: float | None = Field(default=None, ge=0)
    last_end_to_end_ms: float | None = Field(default=None, ge=0)
    last_detection_count: int = Field(ge=0)
    detections_rejected_low_confidence: int = Field(default=0, ge=0)
    detections_rejected_temporal: int = Field(default=0, ge=0)
    detections_rejected_person_verifier: int = Field(default=0, ge=0)
    person_verifier_enabled: bool = False
    person_verifier_loaded: bool = False
    face_detection_enabled: bool = False
    face_detector_loaded: bool = False
    face_last_error: str | None = None
    fall_detection_enabled: bool = False
    fall_pose_model_loaded: bool = False
    fall_observations: int = Field(default=0, ge=0)
    fall_last_error: str | None = None
    model_release: str | None = None
    model_integrity_verified: bool = False
    last_error: str | None = None


class VisionPreview(StrictBaseModel):
    """A bounded JPEG preview supplied by the vision worker, never the source feed."""

    source: str
    timestamp: float
    jpeg_base64: str = Field(min_length=1, max_length=2_000_000)


class Telemetry(StrictBaseModel):
    timestamp: float
    vehicle_id: str | None = Field(default=None, min_length=1, max_length=96)
    system_id: int | None = Field(default=None, ge=1, le=255)
    component_id: int | None = Field(default=None, ge=1, le=255)
    vehicle_type: str | None = Field(default=None, max_length=64)
    flight_mode: str | None = Field(default=None, max_length=64)
    armed: bool | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = Field(ge=0)
    relative_altitude_m: float | None = None
    heading_deg: float = Field(ge=0, lt=360)
    pitch_deg: float = 0
    roll_deg: float = 0
    attitude_valid: bool = False
    ground_speed_mps: float = 0
    vertical_speed_mps: float | None = None
    gps_fix: Literal[
        "NO_GPS", "NO_FIX", "2D", "3D", "DGPS", "RTK_FLOAT", "RTK_FIXED"
    ] | None = None
    satellites_visible: int | None = Field(default=None, ge=0, le=255)
    hdop: float | None = Field(default=None, ge=0)
    vdop: float | None = Field(default=None, ge=0)
    horizontal_accuracy_m: float | None = Field(default=None, ge=0)
    vertical_accuracy_m: float | None = Field(default=None, ge=0)
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    battery_voltage_v: float | None = Field(default=None, ge=0)
    battery_current_a: float | None = None
    link_quality_percent: float | None = Field(default=None, ge=0, le=100)
    range_m: float | None = Field(default=None, ge=0)
    source: str = "mavlink"


class RangeMeasurement(StrictBaseModel):
    timestamp: float
    vehicle_id: str | None = Field(default=None, min_length=1, max_length=96)
    distance_m: float = Field(gt=0)
    min_distance_m: float | None = Field(default=None, ge=0)
    max_distance_m: float | None = Field(default=None, ge=0)
    orientation: Literal["downward", "forward", "unknown"] = "downward"
    source: str = "lidar"


class Geofence(StrictBaseModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=160)
    coordinates: list[tuple[float, float]] = Field(
        min_length=3, max_length=5_000
    )  # latitude, longitude
    restricted: bool = True
    version: str = Field(default="unversioned", min_length=1, max_length=128)


class MissionWaypoint(StrictBaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=128)
    sequence: int = Field(ge=0, le=499)
    command: Literal[
        "WAYPOINT", "TAKEOFF", "LAND", "LOITER_TIME", "RETURN_TO_LAUNCH"
    ] = "WAYPOINT"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = Field(ge=0, le=10_000)
    speed_mps: float | None = Field(default=None, gt=0, le=150)
    hold_time_s: float | None = Field(default=None, ge=0, le=86_400)


class MissionDraft(StrictBaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=UUID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    vehicle_id: str = Field(min_length=1, max_length=96)
    home: Location | None = None
    cruise_speed_mps: float | None = Field(default=None, gt=0, le=150)
    waypoints: list[MissionWaypoint] = Field(default_factory=list, max_length=500)


class MissionRecord(MissionDraft):
    version: int = Field(ge=1)
    state: Literal[
        "DRAFT",
        "VALID",
        "INVALID",
        "READY_TO_UPLOAD",
        "UPLOADING",
        "UPLOADED",
        "UPLOAD_FAILED",
    ] = "DRAFT"
    created_at: float
    updated_at: float
    updated_by: str


class MissionValidationIssue(StrictBaseModel):
    severity: Literal["error", "warning"]
    code: str = Field(min_length=3, max_length=64)
    path: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=300)


class MissionStatistics(StrictBaseModel):
    waypoint_count: int = Field(ge=0)
    total_distance_m: float = Field(ge=0)
    max_range_from_home_m: float | None = Field(default=None, ge=0)
    estimated_duration_s: float | None = Field(default=None, ge=0)


class MissionValidationResult(StrictBaseModel):
    valid: bool
    state: Literal["VALID", "INVALID"]
    issues: list[MissionValidationIssue] = Field(default_factory=list)
    statistics: MissionStatistics


class MissionChange(StrictBaseModel):
    mission: MissionDraft
    expected_version: int | None = Field(default=None, ge=1)
    justification: str = Field(min_length=8, max_length=500)


class MissionDelete(StrictBaseModel):
    expected_version: int = Field(ge=1)
    justification: str = Field(min_length=8, max_length=500)


class MissionPrepareUpload(StrictBaseModel):
    expected_version: int = Field(ge=1)
    justification: str = Field(min_length=8, max_length=500)


class EventProvenance(StrictBaseModel):
    """Reproducible origin and human-review history for a security event."""

    source_id: str | None = None
    source_frame_timestamp: float | None = None
    captured_at: float | None = None
    detector_model: str | None = None
    detector_version: str | None = None
    detector_weights_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    detector_integrity_verified: bool = False
    detector_confidence: float | None = Field(default=None, ge=0, le=1)
    geofence_version: str | None = None
    camera_calibration_version: str | None = None
    camera_calibration_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    camera_extrinsics_version: str | None = None
    camera_extrinsics_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    evidence_id: str | None = None
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    operator_reviewed: bool = False
    reviewed_by: str | None = None
    reviewed_at: float | None = None


class Event(StrictBaseModel):
    id: str = Field(pattern=UUID_PATTERN)
    timestamp: float
    event_type: Literal[
        "geofence_entry",
        "geofence_exit",
        "proximity_warning",
        "loitering",
        "fall_detected",
        "risk_alert",
        "remote_event",
    ]
    severity: Literal["info", "advisory", "warning", "critical"]
    track_id: str
    geofence_id: str
    message: str
    location: Location
    acknowledged: bool = False
    state: Literal[
        "NEW", "ACKNOWLEDGED", "UNDER_REVIEW", "RESOLVED", "DISMISSED"
    ] = "NEW"
    vehicle_id: str | None = None
    camera_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    rule_id: str | None = None
    rule_version: str | None = None
    uncertainty_m: float | None = Field(default=None, ge=0)
    correlation_id: str | None = None
    risk_score: int = Field(default=0, ge=0, le=100)
    risk_factors: list[str] = Field(default_factory=list)
    origin: str = "local"
    provenance: EventProvenance = Field(default_factory=EventProvenance)


class Acknowledge(StrictBaseModel):
    acknowledged: bool = True
    justification: str = Field(default="Operator reviewed event", min_length=3, max_length=500)


class EventTransition(StrictBaseModel):
    state: Literal["ACKNOWLEDGED", "UNDER_REVIEW", "RESOLVED", "DISMISSED"]
    justification: str = Field(min_length=8, max_length=500)


class LegalHoldUpdate(StrictBaseModel):
    legal_hold: bool
    justification: str = Field(min_length=8, max_length=500)


class V2XObservation(StrictBaseModel):
    """Portable context attached to a signed Sentinel V2X event.

    This is a documented project schema, not a claim of SAE/ETSI compliance.
    """

    object_type: str | None = None
    model_class: str | None = None
    track_id: str
    detection_confidence: float | None = Field(default=None, ge=0, le=1)
    observed_at: float | None = None
    source_camera_id: str | None = None
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    velocity_mps: float | None = Field(default=None, ge=0)
    altitude_m: float | None = Field(default=None, ge=0)
    geofence_status: Literal["entered", "exited", "inside", "outside", "unknown"] = (
        "unknown"
    )
    bbox: BBox | None = None


class V2XEnvelope(StrictBaseModel):
    protocol: Literal["sentinel-v2x/1"] = "sentinel-v2x/1"
    message_id: str
    source_id: str
    sent_at: float
    event: Event
    observation: V2XObservation | None = None
    signature: str


class V2XHeartbeat(StrictBaseModel):
    """Signed liveness/capability report from a V2X peer or gateway."""

    protocol: Literal["sentinel-v2x-heartbeat/1"] = "sentinel-v2x-heartbeat/1"
    message_id: str = Field(min_length=8, max_length=128)
    device_id: str = Field(
        min_length=2, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]+$"
    )
    device_type: Literal["drone", "camera", "vehicle", "infrastructure", "gateway"]
    sent_at: float
    sequence: int = Field(ge=0)
    reported_status: Literal["online", "degraded", "maintenance"] = "online"
    transport: Literal["mqtt", "https", "v2x_gateway"] = "mqtt"
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    firmware_version: str | None = Field(default=None, max_length=96)
    signature: str


class V2XDeviceStatus(StrictBaseModel):
    """Sanitised operator view; it never includes peer credentials."""

    device_id: str
    device_type: Literal["drone", "camera", "vehicle", "infrastructure", "gateway"]
    link_status: Literal["online", "degraded", "maintenance", "offline"]
    transport: Literal["mqtt", "https", "v2x_gateway"]
    capabilities: list[str] = Field(default_factory=list)
    firmware_version: str | None = None
    last_seen_at: float
    reported_at: float
    age_s: float = Field(ge=0)
    clock_skew_s: float
    last_sequence: int = Field(ge=0)


class EvidenceRequest(StrictBaseModel):
    """An asynchronous request for more evidence; never an enforcement command."""

    request_id: str
    event_id: str
    track_id: str
    requested_at: float
    expires_at: float
    reason: str
    source_camera_id: str | None = None
    requested_camera_ids: list[str] = Field(default_factory=list)
    object_type: str | None = None
    detection_confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ref: str | None = None
    # A second-opinion object review can run before drone telemetry is linked;
    # high-risk events continue to carry a geographic location.
    location: Location | None = None
    advisory_only: Literal[True] = True


class EvidenceVerification(StrictBaseModel):
    """Provider/LLM output retained as review evidence, never a risk-rule input."""

    request_id: str
    event_id: str
    provider: str
    verdict: Literal["confirmed", "contradicted", "inconclusive", "unavailable"]
    reviewed_at: float
    rationale: str = Field(min_length=1, max_length=1000)
    evidence_source_ids: list[str] = Field(default_factory=list)
    advisory_only: Literal[True] = True


class SecurityFinding(StrictBaseModel):
    """A deterministic defensive-integrity finding, never a control command."""

    id: str
    timestamp: float
    source_id: str
    category: Literal[
        "telemetry_integrity",
        "v2x_authentication",
        "transport_posture",
        "physical_safety",
    ]
    code: str
    severity: Literal["info", "warning", "critical"]
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, float | str] = Field(default_factory=dict)
    recommended_action: str = Field(min_length=1, max_length=300)
    advisory_only: Literal[True] = True


class SecurityAdvisory(StrictBaseModel):
    """Sanitised LLM text summary of deterministic security findings."""

    request_id: str
    finding_ids: list[str] = Field(min_length=1, max_length=8)
    provider: str
    reviewed_at: float
    status: Literal["available", "unavailable"]
    summary: str = Field(min_length=1, max_length=1000)
    recommendations: list[str] = Field(default_factory=list, max_length=5)
    advisory_only: Literal[True] = True
