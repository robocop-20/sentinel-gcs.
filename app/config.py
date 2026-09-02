import os
from dataclasses import dataclass
from functools import lru_cache


def _llm_key_for(provider: str) -> str:
    """Resolve only a key that belongs to the selected provider.

    A generic LLM_API_KEY is accepted for backwards compatibility. Provider-
    specific keys are never borrowed by another adapter: sending an xAI key to
    Google (or the reverse) produces misleading configuration and failed calls.
    """
    generic = os.getenv("LLM_API_KEY", "").strip()
    if generic:
        return generic
    selected = provider.strip().lower()
    if selected == "openrouter":
        return os.getenv("OPENROUTER_API_KEY", "").strip()
    if selected in {"xai", "grok"}:
        return os.getenv("XAI_API_KEY", "").strip()
    if selected in {"google", "gemini"}:
        return (
            os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        ).strip()
    return ""


@dataclass(frozen=True)
class Settings:
    """Environment-only settings; Compose supplies .env to containers."""

    api_port: int = int(os.getenv("API_PORT", "8080"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    service_health_port: int = int(os.getenv("SERVICE_HEALTH_PORT", "8091"))
    map_tile_url_template: str = os.getenv(
        "MAP_TILE_URL_TEMPLATE",
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    ).strip()
    map_tile_attribution: str = os.getenv(
        "MAP_TILE_ATTRIBUTION", "© OpenStreetMap contributors"
    ).strip()
    street_view_url_template: str = os.getenv(
        "STREET_VIEW_URL_TEMPLATE",
        "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat}%2C{lon}",
    ).strip()
    cors_origins: str = os.getenv(
        "CORS_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080"
    )
    auth_enabled: bool = os.getenv("AUTH_ENABLED", "true").lower() == "true"
    auth_issuer: str = os.getenv("AUTH_ISSUER", "sentinel-ground-station")
    auth_audience: str = os.getenv("AUTH_AUDIENCE", "sentinel-api")
    auth_access_token_minutes: int = int(os.getenv("AUTH_ACCESS_TOKEN_MINUTES", "15"))
    auth_signing_key_file: str = os.getenv(
        "AUTH_SIGNING_KEY_FILE", "/run/secrets/jwt-signing-key"
    )
    auth_users_file: str = os.getenv("AUTH_USERS_FILE", "/run/secrets/auth-users.json")
    auth_service_credentials_file: str = os.getenv(
        "AUTH_SERVICE_CREDENTIALS_FILE", "/run/secrets/service-credentials.json"
    )
    service_client_id: str = os.getenv("SERVICE_CLIENT_ID", "")
    service_client_secret_file: str = os.getenv("SERVICE_CLIENT_SECRET_FILE", "")
    service_ca_cert: str = os.getenv("SERVICE_CA_CERT", "")
    service_client_cert: str = os.getenv("SERVICE_CLIENT_CERT", "")
    service_client_key: str = os.getenv("SERVICE_CLIENT_KEY", "")
    request_body_limit_bytes: int = int(
        os.getenv("REQUEST_BODY_LIMIT_BYTES", "2500000")
    )
    api_rate_limit_per_minute: int = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "240"))
    # Vision and telemetry services publish small, signed batches at video
    # cadence.  They need a distinct ceiling from interactive browser traffic
    # so an otherwise healthy 20–30 FPS worker cannot trip the public API
    # limiter and put the ground station into a false degraded state.
    service_rate_limit_per_minute: int = int(
        os.getenv("SERVICE_RATE_LIMIT_PER_MINUTE", "1800")
    )
    preview_rate_limit_per_minute: int = int(
        os.getenv("PREVIEW_RATE_LIMIT_PER_MINUTE", "600")
    )
    auth_rate_limit_per_minute: int = int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "10"))
    websocket_max_clients: int = int(os.getenv("WEBSOCKET_MAX_CLIENTS", "32"))
    mqtt_host: str = os.getenv("MQTT_HOST", "mqtt")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://sentinel@postgis:5432/sentinel"
    )
    camera_fov_horizontal_deg: float = float(
        os.getenv("CAMERA_FOV_HORIZONTAL_DEG", "92")
    )
    camera_fov_vertical_deg: float = float(os.getenv("CAMERA_FOV_VERTICAL_DEG", "60"))
    camera_mount_pitch_deg: float = float(os.getenv("CAMERA_MOUNT_PITCH_DEG", "-90"))
    camera_fx_px: float = float(os.getenv("CAMERA_FX_PX", "0"))
    camera_fy_px: float = float(os.getenv("CAMERA_FY_PX", "0"))
    camera_cx_px: float = float(os.getenv("CAMERA_CX_PX", "0"))
    camera_cy_px: float = float(os.getenv("CAMERA_CY_PX", "0"))
    camera_calibration_file: str = os.getenv("CAMERA_CALIBRATION_FILE", "")
    camera_extrinsics_file: str = os.getenv("CAMERA_EXTRINSICS_FILE", "")
    enable_ray_plane_geolocation: bool = (
        os.getenv("ENABLE_RAY_PLANE_GEOLOCATION", "false").lower() == "true"
    )
    camera_to_body_matrix: str = os.getenv(
        "CAMERA_TO_BODY_MATRIX", "0,-1,0,1,0,0,0,0,1"
    )
    lidar_max_age_s: float = float(os.getenv("LIDAR_MAX_AGE_S", "1.5"))
    lidar_orientation: str = os.getenv("LIDAR_ORIENTATION", "downward")
    telemetry_max_skew_s: float = float(os.getenv("TELEMETRY_MAX_SKEW_S", "1.0"))
    pipeline_queue_size: int = int(os.getenv("PIPELINE_QUEUE_SIZE", "512"))
    durable_queue_path: str = os.getenv(
        "DURABLE_QUEUE_PATH", "/var/lib/sentinel/durable-queue.sqlite3"
    )
    durable_queue_max_records: int = int(
        os.getenv("DURABLE_QUEUE_MAX_RECORDS", "100000")
    )
    durable_queue_max_bytes: int = int(
        os.getenv("DURABLE_QUEUE_MAX_BYTES", str(512 * 1024 * 1024))
    )
    delivery_retry_base_s: float = float(os.getenv("DELIVERY_RETRY_BASE_S", "0.5"))
    delivery_retry_max_s: float = float(os.getenv("DELIVERY_RETRY_MAX_S", "60"))
    delivery_max_attempts: int = int(os.getenv("DELIVERY_MAX_ATTEMPTS", "8"))
    delivery_circuit_failure_threshold: int = int(
        os.getenv("DELIVERY_CIRCUIT_FAILURE_THRESHOLD", "5")
    )
    delivery_circuit_cooldown_s: float = float(
        os.getenv("DELIVERY_CIRCUIT_COOLDOWN_S", "15")
    )
    detection_idempotency_ttl_s: float = float(
        os.getenv("DETECTION_IDEMPOTENCY_TTL_S", "120")
    )
    event_idempotency_window_s: float = float(
        os.getenv("EVENT_IDEMPOTENCY_WINDOW_S", "30")
    )
    v2x_idempotency_ttl_s: float = float(
        os.getenv("V2X_IDEMPOTENCY_TTL_S", "3600")
    )
    video_source: str = os.getenv("VIDEO_SOURCE", "")
    video_backend: str = os.getenv("VIDEO_BACKEND", "")
    # Applied at the perception boundary so every downstream model receives
    # the same camera orientation. Supported values: 0, 90, 180, 270.
    video_rotation_deg: int = int(os.getenv("VIDEO_ROTATION_DEG", "0"))
    camera_id: str = os.getenv("CAMERA_ID", "camera-01")
    camera_vehicle_id: str | None = os.getenv("CAMERA_VEHICLE_ID", "").strip() or None
    yolo_model: str = os.getenv("YOLO_MODEL", "yolo11s.pt")
    yolo_device: str = os.getenv("YOLO_DEVICE", "")
    # A local, versioned ByteTrack policy.  Do not rely on a package-default
    # tracker configuration changing underneath a deployed camera system.
    tracker_config: str = os.getenv(
        "TRACKER_CONFIG", "/service/app/sentinel_bytetrack.yaml"
    )
    detection_confidence: float = float(os.getenv("DETECTION_CONFIDENCE", "0.35"))
    person_candidate_confidence: float = float(
        os.getenv("PERSON_CANDIDATE_CONFIDENCE", "0.25")
    )
    vessel_candidate_confidence: float = float(
        os.getenv("VESSEL_CANDIDATE_CONFIDENCE", "0.20")
    )
    vehicle_candidate_confidence: float = float(
        os.getenv("VEHICLE_CANDIDATE_CONFIDENCE", "0.20")
    )
    container_candidate_confidence: float = float(
        os.getenv("CONTAINER_CANDIDATE_CONFIDENCE", "0.25")
    )
    # Detector candidates may be low for ByteTrack association, but only
    # stronger observations are allowed into the operator/event pipeline.
    object_publish_confidence: float = float(
        os.getenv("OBJECT_PUBLISH_CONFIDENCE", "0.35")
    )
    person_publish_confidence: float = float(
        os.getenv("PERSON_PUBLISH_CONFIDENCE", "0.55")
    )
    vessel_publish_confidence: float = float(
        os.getenv("VESSEL_PUBLISH_CONFIDENCE", "0.35")
    )
    vehicle_publish_confidence: float = float(
        os.getenv("VEHICLE_PUBLISH_CONFIDENCE", "0.40")
    )
    container_publish_confidence: float = float(
        os.getenv("CONTAINER_PUBLISH_CONFIDENCE", "0.50")
    )
    # Optional local cross-model veto for marginal YOLO person detections.
    # It is a generic COCO person detector, not facial recognition.
    enable_person_verifier: bool = (
        os.getenv("ENABLE_PERSON_VERIFIER", "false").lower() == "true"
    )
    person_verifier_max_yolo_confidence: float = float(
        os.getenv("PERSON_VERIFIER_MAX_YOLO_CONFIDENCE", "0.78")
    )
    person_verifier_detection_confidence: float = float(
        os.getenv("PERSON_VERIFIER_DETECTION_CONFIDENCE", "0.60")
    )
    person_verifier_min_iou: float = float(os.getenv("PERSON_VERIFIER_MIN_IOU", "0.25"))
    person_verifier_cache_s: float = float(os.getenv("PERSON_VERIFIER_CACHE_S", "1.0"))
    person_verifier_cache_dir: str = os.getenv(
        "PERSON_VERIFIER_CACHE_DIR", "/models/person-verifier"
    )
    # Explicit field-acceptance limits. A dashboard must never imply that a
    # prototype is deployment-ready merely because its containers are up.
    field_min_inference_fps: float = float(os.getenv("FIELD_MIN_INFERENCE_FPS", "20"))
    field_max_end_to_end_ms: float = float(os.getenv("FIELD_MAX_END_TO_END_MS", "100"))
    frame_interval: int = int(os.getenv("FRAME_INTERVAL", "1"))
    vision_img_size: int = int(os.getenv("VISION_IMG_SIZE", "640"))
    vision_max_detections: int = int(os.getenv("VISION_MAX_DETECTIONS", "100"))
    vision_reconnect_delay_s: float = float(
        os.getenv("VISION_RECONNECT_DELAY_S", "0.5")
    )
    vision_reconnect_max_delay_s: float = float(
        os.getenv("VISION_RECONNECT_MAX_DELAY_S", "15")
    )
    vision_status_interval_s: float = float(os.getenv("VISION_STATUS_INTERVAL_S", "2"))
    vision_metrics_stale_s: float = float(os.getenv("VISION_METRICS_STALE_S", "8"))
    vision_api_timeout_s: float = float(os.getenv("VISION_API_TIMEOUT_S", "1"))
    vision_cpu_threads: int = int(os.getenv("VISION_CPU_THREADS", "0"))
    enable_annotated_preview: bool = (
        os.getenv("ENABLE_ANNOTATED_PREVIEW", "true").lower() == "true"
    )
    preview_fps: float = float(os.getenv("PREVIEW_FPS", "5"))
    preview_max_dimension_px: int = int(os.getenv("PREVIEW_MAX_DIMENSION_PX", "960"))
    preview_jpeg_quality: int = int(os.getenv("PREVIEW_JPEG_QUALITY", "80"))
    # Display-only EMA for stable on-screen confidence. Risk uses raw YOLO score.
    confidence_display_ema_alpha: float = float(
        os.getenv("CONFIDENCE_DISPLAY_EMA_ALPHA", "0.25")
    )
    confidence_track_ttl_s: float = float(os.getenv("CONFIDENCE_TRACK_TTL_S", "30"))
    # Standard COCO YOLO11 detects person/boat/car/truck/bus/motorcycle.
    # `small_boat` and `cargo_vessel` become active only when a validated
    # port-trained YOLO model with those labels is supplied through YOLO_MODEL.
    target_object_classes: str = os.getenv(
        "TARGET_OBJECT_CLASSES",
        "person,boat,vessel,small_boat,cargo_vessel,car,truck,bus,motorcycle,vehicle",
    )
    motion_moving_threshold_px_s: float = float(
        os.getenv("MOTION_MOVING_THRESHOLD_PX_S", "15")
    )
    motion_track_ttl_s: float = float(os.getenv("MOTION_TRACK_TTL_S", "3"))
    # Publish only temporally confirmed ByteTrack IDs to reduce one-frame false positives.
    min_track_confirmation_frames: int = int(
        os.getenv("MIN_TRACK_CONFIRMATION_FRAMES", "3")
    )
    person_confirmation_frames: int = int(
        os.getenv("PERSON_CONFIRMATION_FRAMES", "5")
    )
    vessel_confirmation_frames: int = int(
        os.getenv("VESSEL_CONFIRMATION_FRAMES", "3")
    )
    vehicle_confirmation_frames: int = int(
        os.getenv("VEHICLE_CONFIRMATION_FRAMES", "3")
    )
    container_confirmation_frames: int = int(
        os.getenv("CONTAINER_CONFIRMATION_FRAMES", "4")
    )
    track_confirmation_max_gap_s: float = float(
        os.getenv("TRACK_CONFIRMATION_MAX_GAP_S", "1.5")
    )
    track_evidence_window: int = int(os.getenv("TRACK_EVIDENCE_WINDOW", "8"))
    track_min_class_stability: float = float(
        os.getenv("TRACK_MIN_CLASS_STABILITY", "0.80")
    )
    person_track_min_mean_confidence: float = float(
        os.getenv("PERSON_TRACK_MIN_MEAN_CONFIDENCE", "0.62")
    )
    object_track_min_mean_confidence: float = float(
        os.getenv("OBJECT_TRACK_MIN_MEAN_CONFIDENCE", "0.50")
    )
    vessel_track_min_mean_confidence: float = float(
        os.getenv("VESSEL_TRACK_MIN_MEAN_CONFIDENCE", "0.50")
    )
    vehicle_track_min_mean_confidence: float = float(
        os.getenv("VEHICLE_TRACK_MIN_MEAN_CONFIDENCE", "0.52")
    )
    container_track_min_mean_confidence: float = float(
        os.getenv("CONTAINER_TRACK_MIN_MEAN_CONFIDENCE", "0.58")
    )
    # UI/API active-track state is ephemeral; persistence retains the history.
    active_track_ttl_s: float = float(os.getenv("ACTIVE_TRACK_TTL_S", "8"))
    track_occluded_after_s: float = float(
        os.getenv("TRACK_OCCLUDED_AFTER_S", "0.75")
    )
    track_temporarily_lost_after_s: float = float(
        os.getenv("TRACK_TEMPORARILY_LOST_AFTER_S", "2.0")
    )
    track_reacquired_after_s: float = float(
        os.getenv("TRACK_REACQUIRED_AFTER_S", "0.75")
    )
    # A port-model release can be SHA-256 checked against a local manifest.
    model_manifest_path: str = os.getenv("MODEL_MANIFEST_PATH", "")
    require_model_manifest: bool = (
        os.getenv("REQUIRE_MODEL_MANIFEST", "false").lower() == "true"
    )
    enable_face_detection: bool = (
        os.getenv("ENABLE_FACE_DETECTION", "false").lower() == "true"
    )
    face_detector_model_path: str = os.getenv(
        "FACE_DETECTOR_MODEL_PATH", "/models/face/yunet.onnx"
    )
    face_detection_confidence: float = float(
        os.getenv("FACE_DETECTION_CONFIDENCE", "0.65")
    )
    face_detection_interval: int = int(os.getenv("FACE_DETECTION_INTERVAL", "3"))
    face_detection_max_dimension_px: int = int(
        os.getenv("FACE_DETECTION_MAX_DIMENSION_PX", "640")
    )
    face_quality_min_score: float = float(os.getenv("FACE_QUALITY_MIN_SCORE", "0.65"))
    # Anonymous spatial continuity only; this is not facial recognition.
    face_track_ttl_s: float = float(os.getenv("FACE_TRACK_TTL_S", "2.0"))
    face_track_iou_threshold: float = float(
        os.getenv("FACE_TRACK_IOU_THRESHOLD", "0.25")
    )
    privacy_blur_faces: bool = os.getenv("PRIVACY_BLUR_FACES", "true").lower() == "true"
    # Local, non-biometric fall observation. The pose model is invoked only
    # when YOLO11 has already confirmed a person track, and its output never
    # changes person identity or normal object-tracking decisions.
    enable_fall_detection: bool = (
        os.getenv("ENABLE_FALL_DETECTION", "false").lower() == "true"
    )
    fall_pose_model_path: str = os.getenv(
        "FALL_POSE_MODEL_PATH", "/models/yolo11n-pose.pt"
    )
    fall_pose_img_size: int = int(os.getenv("FALL_POSE_IMG_SIZE", "320"))
    fall_pose_interval: int = int(os.getenv("FALL_POSE_INTERVAL", "2"))
    fall_pose_confidence: float = float(os.getenv("FALL_POSE_CONFIDENCE", "0.45"))
    fall_min_confidence: float = float(os.getenv("FALL_MIN_CONFIDENCE", "0.68"))
    fall_min_sustained_frames: int = int(os.getenv("FALL_MIN_SUSTAINED_FRAMES", "3"))
    fall_confirmation_window_s: float = float(
        os.getenv("FALL_CONFIRMATION_WINDOW_S", "2.5")
    )
    fall_event_cooldown_s: float = float(os.getenv("FALL_EVENT_COOLDOWN_S", "45"))
    mavlink_endpoint: str = os.getenv("MAVLINK_ENDPOINT", "udp:0.0.0.0:14550")
    mavlink_baud: int = int(os.getenv("MAVLINK_BAUD", "57600"))
    risk_timezone: str = os.getenv("RISK_TIMEZONE", "Asia/Kolkata")
    risk_quiet_start_hour: int = int(os.getenv("RISK_QUIET_START_HOUR", "20"))
    risk_quiet_end_hour: int = int(os.getenv("RISK_QUIET_END_HOUR", "6"))
    # Deterministic anonymous-track behaviour analytics require a geolocated track.
    enable_behavior_analytics: bool = (
        os.getenv("ENABLE_BEHAVIOR_ANALYTICS", "true").lower() == "true"
    )
    loiter_window_s: float = float(os.getenv("LOITER_WINDOW_S", "120"))
    loiter_radius_m: float = float(os.getenv("LOITER_RADIUS_M", "8"))
    proximity_warning_distance_m: float = float(
        os.getenv("PROXIMITY_WARNING_DISTANCE_M", "8")
    )
    behavior_event_cooldown_s: float = float(
        os.getenv("BEHAVIOR_EVENT_COOLDOWN_S", "300")
    )
    behavior_track_ttl_s: float = float(os.getenv("BEHAVIOR_TRACK_TTL_S", "900"))
    enable_v2x: bool = os.getenv("ENABLE_V2X", "false").lower() == "true"
    v2x_source_id: str = os.getenv("V2X_SOURCE_ID", "ground-station-01")
    v2x_shared_secret: str = os.getenv("V2X_SHARED_SECRET", "")
    v2x_allowed_sources: str = os.getenv("V2X_ALLOWED_SOURCES", "")
    v2x_events_topic: str = os.getenv("V2X_EVENTS_TOPIC", "sentinel/v2x/events")
    v2x_heartbeats_topic: str = os.getenv(
        "V2X_HEARTBEATS_TOPIC", "sentinel/v2x/heartbeats"
    )
    v2x_max_age_s: int = int(os.getenv("V2X_MAX_AGE_S", "30"))
    v2x_heartbeat_interval_s: float = float(os.getenv("V2X_HEARTBEAT_INTERVAL_S", "5"))
    v2x_device_offline_s: float = float(os.getenv("V2X_DEVICE_OFFLINE_S", "15"))
    mqtt_username: str = os.getenv("MQTT_USERNAME", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_ca_cert: str = os.getenv("MQTT_CA_CERT", "")
    mqtt_client_cert: str = os.getenv("MQTT_CLIENT_CERT", "")
    mqtt_client_key: str = os.getenv("MQTT_CLIENT_KEY", "")
    mqtt_reconnect_min_s: int = int(os.getenv("MQTT_RECONNECT_MIN_S", "1"))
    mqtt_reconnect_max_s: int = int(os.getenv("MQTT_RECONNECT_MAX_S", "30"))
    mqtt_publish_timeout_s: float = float(os.getenv("MQTT_PUBLISH_TIMEOUT_S", "5"))
    mqtt_dead_letter_topic: str = os.getenv(
        "MQTT_DEAD_LETTER_TOPIC", "sentinel/dead-letter/events"
    )
    database_write_pool_size: int = int(os.getenv("DATABASE_WRITE_POOL_SIZE", "4"))
    database_read_pool_size: int = int(os.getenv("DATABASE_READ_POOL_SIZE", "4"))
    history_query_max_records: int = int(
        os.getenv("HISTORY_QUERY_MAX_RECORDS", "2000")
    )
    history_query_max_span_s: float = float(
        os.getenv("HISTORY_QUERY_MAX_SPAN_S", "86400")
    )
    # Defensive integrity monitoring. Findings are advisory and do not issue
    # flight, transport, or containment commands.
    enable_security_monitor: bool = (
        os.getenv("ENABLE_SECURITY_MONITOR", "true").lower() == "true"
    )
    security_monitor_interval_s: float = float(
        os.getenv("SECURITY_MONITOR_INTERVAL_S", "1")
    )
    security_telemetry_stale_s: float = float(
        os.getenv("SECURITY_TELEMETRY_STALE_S", "5")
    )
    security_max_clock_skew_s: float = float(
        os.getenv("SECURITY_MAX_CLOCK_SKEW_S", "3")
    )
    security_max_ground_speed_mps: float = float(
        os.getenv("SECURITY_MAX_GROUND_SPEED_MPS", "70")
    )
    security_max_heading_rate_deg_s: float = float(
        os.getenv("SECURITY_MAX_HEADING_RATE_DEG_S", "540")
    )
    security_lidar_altitude_delta_m: float = float(
        os.getenv("SECURITY_LIDAR_ALTITUDE_DELTA_M", "8")
    )
    security_level_attitude_deg: float = float(
        os.getenv("SECURITY_LEVEL_ATTITUDE_DEG", "15")
    )
    security_min_link_quality_percent: float = float(
        os.getenv("SECURITY_MIN_LINK_QUALITY_PERCENT", "20")
    )
    security_finding_cooldown_s: float = float(
        os.getenv("SECURITY_FINDING_COOLDOWN_S", "30")
    )
    security_findings_topic: str = os.getenv(
        "SECURITY_FINDINGS_TOPIC", "ground/security/findings"
    )
    security_advisories_topic: str = os.getenv(
        "SECURITY_ADVISORIES_TOPIC", "ground/security/advisories"
    )
    # Existing local broker mode is plaintext development transport. Enabling
    # TLS needs broker certificates and is reported by the security health API.
    mqtt_tls_enabled: bool = os.getenv("MQTT_TLS_ENABLED", "false").lower() == "true"
    enable_llm_verification: bool = (
        os.getenv("ENABLE_LLM_VERIFICATION", "false").lower() == "true"
    )
    llm_verification_min_risk: int = int(os.getenv("LLM_VERIFICATION_MIN_RISK", "75"))
    evidence_request_ttl_s: int = int(os.getenv("EVIDENCE_REQUEST_TTL_S", "60"))
    evidence_camera_ids: str = os.getenv("EVIDENCE_CAMERA_IDS", "")
    evidence_requests_topic: str = os.getenv(
        "EVIDENCE_REQUESTS_TOPIC", "ground/evidence/requests"
    )
    # Object evidence is disabled by default because it persists camera pixels.
    # It is deliberately separate from face detection and never saves face crops.
    enable_evidence_capture: bool = (
        os.getenv("ENABLE_EVIDENCE_CAPTURE", "false").lower() == "true"
    )
    evidence_dir: str = os.getenv("EVIDENCE_DIR", "/evidence")
    evidence_encryption_key_file: str = os.getenv(
        "EVIDENCE_ENCRYPTION_KEY_FILE", "/run/secrets/evidence-encryption-key"
    )
    evidence_capture_interval_s: float = float(
        os.getenv("EVIDENCE_CAPTURE_INTERVAL_S", "2")
    )
    evidence_max_dimension_px: int = int(os.getenv("EVIDENCE_MAX_DIMENSION_PX", "640"))
    evidence_jpeg_quality: int = int(os.getenv("EVIDENCE_JPEG_QUALITY", "85"))
    enable_evidence_retention: bool = (
        os.getenv("ENABLE_EVIDENCE_RETENTION", "true").lower() == "true"
    )
    evidence_retention_days: int = int(os.getenv("EVIDENCE_RETENTION_DAYS", "30"))
    evidence_retention_interval_s: float = float(
        os.getenv("EVIDENCE_RETENTION_INTERVAL_S", "3600")
    )
    # Advisory providers: OpenRouter's free router or an operator-funded xAI
    # Grok API key. Keys are never logged or returned.
    llm_provider: str = os.getenv("LLM_PROVIDER", "openrouter")
    llm_api_key: str = _llm_key_for(llm_provider)
    llm_model: str = os.getenv("LLM_MODEL", "openrouter/free")
    # A separate, explicit external-image consent gate. A key alone cannot
    # enable network egress of camera-derived evidence.
    enable_external_llm_egress: bool = (
        os.getenv("ENABLE_EXTERNAL_LLM_EGRESS", "false").lower() == "true"
    )
    llm_request_timeout_s: float = float(os.getenv("LLM_REQUEST_TIMEOUT_S", "20"))
    llm_max_image_bytes: int = int(os.getenv("LLM_MAX_IMAGE_BYTES", "1000000"))
    llm_max_queue: int = int(os.getenv("LLM_MAX_QUEUE", "8"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "2"))
    llm_retry_backoff_s: float = float(os.getenv("LLM_RETRY_BACKOFF_S", "1"))
    llm_circuit_failure_threshold: int = int(
        os.getenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "3")
    )
    llm_circuit_cooldown_s: float = float(os.getenv("LLM_CIRCUIT_COOLDOWN_S", "60"))
    failsafe_max_queue_ratio: float = float(
        os.getenv("FAILSAFE_MAX_QUEUE_RATIO", "0.80")
    )
    # A bounded second-opinion path for a confirmed non-person object.  This
    # is separate from high-risk event review so a missing GPS/LiDAR feed does
    # not prevent an approved visual review from ever being exercised.
    enable_llm_detection_advisory: bool = (
        os.getenv("ENABLE_LLM_DETECTION_ADVISORY", "false").lower() == "true"
    )
    llm_advisory_min_confidence: float = float(
        os.getenv("LLM_ADVISORY_MIN_CONFIDENCE", "0.60")
    )
    llm_advisory_track_cooldown_s: float = float(
        os.getenv("LLM_ADVISORY_TRACK_COOLDOWN_S", "90")
    )
    # Security summaries are text-only and require a separate consent gate.
    # Object-crop consent never enables telemetry/network-context egress.
    enable_llm_security_advisory: bool = (
        os.getenv("ENABLE_LLM_SECURITY_ADVISORY", "false").lower() == "true"
    )
    enable_external_llm_text_egress: bool = (
        os.getenv("ENABLE_EXTERNAL_LLM_TEXT_EGRESS", "false").lower() == "true"
    )

    def validate(self) -> None:
        """Reject internally inconsistent safety/performance configuration."""
        errors: list[str] = []
        confidences = {
            "DETECTION_CONFIDENCE": self.detection_confidence,
            "PERSON_CANDIDATE_CONFIDENCE": self.person_candidate_confidence,
            "VESSEL_CANDIDATE_CONFIDENCE": self.vessel_candidate_confidence,
            "VEHICLE_CANDIDATE_CONFIDENCE": self.vehicle_candidate_confidence,
            "CONTAINER_CANDIDATE_CONFIDENCE": self.container_candidate_confidence,
            "OBJECT_PUBLISH_CONFIDENCE": self.object_publish_confidence,
            "PERSON_PUBLISH_CONFIDENCE": self.person_publish_confidence,
            "VESSEL_PUBLISH_CONFIDENCE": self.vessel_publish_confidence,
            "VEHICLE_PUBLISH_CONFIDENCE": self.vehicle_publish_confidence,
            "CONTAINER_PUBLISH_CONFIDENCE": self.container_publish_confidence,
            "TRACK_MIN_CLASS_STABILITY": self.track_min_class_stability,
            "PERSON_TRACK_MIN_MEAN_CONFIDENCE": (
                self.person_track_min_mean_confidence
            ),
            "VESSEL_TRACK_MIN_MEAN_CONFIDENCE": (
                self.vessel_track_min_mean_confidence
            ),
            "VEHICLE_TRACK_MIN_MEAN_CONFIDENCE": (
                self.vehicle_track_min_mean_confidence
            ),
            "CONTAINER_TRACK_MIN_MEAN_CONFIDENCE": (
                self.container_track_min_mean_confidence
            ),
        }
        errors.extend(
            f"{name} must be between 0 and 1"
            for name, value in confidences.items()
            if not 0 <= value <= 1
        )
        for object_class in ("person", "vessel", "vehicle", "container"):
            if self.candidate_confidence_for(
                object_class
            ) > self.publish_confidence_for(object_class):
                errors.append(
                    f"{object_class} candidate confidence must not exceed its "
                    "publish confidence"
                )
            if self.confirmation_frames_for(object_class) < 1:
                errors.append(
                    f"{object_class} confirmation frames must be at least one"
                )
        if not 0 < self.camera_fov_horizontal_deg < 180:
            errors.append("CAMERA_FOV_HORIZONTAL_DEG must be between 0 and 180")
        if not 0 < self.camera_fov_vertical_deg < 180:
            errors.append("CAMERA_FOV_VERTICAL_DEG must be between 0 and 180")
        if (
            self.enable_ray_plane_geolocation
            and not self.camera_calibration_file
            and (self.camera_fx_px <= 0 or self.camera_fy_px <= 0)
        ):
            errors.append(
                "ray-plane geolocation requires positive CAMERA_FX_PX and CAMERA_FY_PX"
            )
        if self.telemetry_max_skew_s <= 0:
            errors.append("TELEMETRY_MAX_SKEW_S must be positive")
        if self.lidar_max_age_s <= 0:
            errors.append("LIDAR_MAX_AGE_S must be positive")
        if self.pipeline_queue_size < 1:
            errors.append("PIPELINE_QUEUE_SIZE must be at least one")
        if self.websocket_max_clients < 1:
            errors.append("WEBSOCKET_MAX_CLIENTS must be at least one")
        if not 1 <= self.history_query_max_records <= 10000:
            errors.append("HISTORY_QUERY_MAX_RECORDS must be between 1 and 10000")
        if not 60 <= self.history_query_max_span_s <= 604800:
            errors.append("HISTORY_QUERY_MAX_SPAN_S must be between 60 and 604800")
        if self.preview_fps <= 0:
            errors.append("PREVIEW_FPS must be positive")
        if not (
            self.track_occluded_after_s
            <= self.track_temporarily_lost_after_s
            <= self.active_track_ttl_s
        ):
            errors.append(
                "track lifecycle thresholds must be ordered: occluded <= "
                "temporarily lost <= active TTL"
            )
        if self.enable_v2x and not self.v2x_shared_secret.strip():
            errors.append("ENABLE_V2X requires V2X_SHARED_SECRET")
        if self.enable_v2x and not self.allowed_v2x_sources:
            errors.append("ENABLE_V2X requires at least one V2X_ALLOWED_SOURCES peer")
        try:
            self.camera_to_body_rotation
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            raise ValueError("Invalid Sentinel configuration: " + "; ".join(errors))

    @property
    def target_classes(self) -> set[str]:
        return {
            value.strip().lower()
            for value in self.target_object_classes.split(",")
            if value.strip()
        }

    @property
    def llm_advisory_classes(self) -> set[str]:
        # External review is restricted to non-person objects.  The local
        # system never sends a person crop to an external provider.
        values = os.getenv("LLM_ADVISORY_OBJECT_CLASSES", "vessel,vehicle,container")
        return {value.strip().lower() for value in values.split(",") if value.strip()}

    @property
    def allowed_v2x_sources(self) -> set[str]:
        return {
            value.strip()
            for value in self.v2x_allowed_sources.split(",")
            if value.strip()
        }

    def publish_confidence_for(self, object_class: str) -> float:
        return {
            "person": self.person_publish_confidence,
            "vessel": self.vessel_publish_confidence,
            "vehicle": self.vehicle_publish_confidence,
            "container": self.container_publish_confidence,
        }.get(object_class, self.object_publish_confidence)

    def candidate_confidence_for(self, object_class: str) -> float:
        return {
            "person": self.person_candidate_confidence,
            "vessel": self.vessel_candidate_confidence,
            "vehicle": self.vehicle_candidate_confidence,
            "container": self.container_candidate_confidence,
        }.get(object_class, self.detection_confidence)

    @property
    def minimum_candidate_confidence(self) -> float:
        return min(
            self.detection_confidence,
            self.person_candidate_confidence,
            self.vessel_candidate_confidence,
            self.vehicle_candidate_confidence,
            self.container_candidate_confidence,
        )

    def confirmation_frames_for(self, object_class: str) -> int:
        return {
            "person": self.person_confirmation_frames,
            "vessel": self.vessel_confirmation_frames,
            "vehicle": self.vehicle_confirmation_frames,
            "container": self.container_confirmation_frames,
        }.get(object_class, self.min_track_confirmation_frames)

    def track_mean_confidence_for(self, object_class: str) -> float:
        return {
            "person": self.person_track_min_mean_confidence,
            "vessel": self.vessel_track_min_mean_confidence,
            "vehicle": self.vehicle_track_min_mean_confidence,
            "container": self.container_track_min_mean_confidence,
        }.get(object_class, self.object_track_min_mean_confidence)

    @property
    def release_expected_classes(self) -> set[str]:
        # COCO aliases are normalised by the worker. A maritime custom model
        # retains its two precise labels in the release manifest while runtime
        # tracks both under the canonical `vessel` risk category.
        maritime_classes = {"small_boat", "cargo_vessel"}
        if maritime_classes.issubset(self.target_classes):
            return maritime_classes
        return {
            value
            for value in self.target_classes
            if value in {"person", "vessel", "vehicle", "container"}
        }

    @property
    def camera_to_body_rotation(self) -> tuple[float, ...]:
        values = tuple(
            float(value.strip()) for value in self.camera_to_body_matrix.split(",")
        )
        if len(values) != 9:
            raise ValueError(
                "CAMERA_TO_BODY_MATRIX must contain nine comma-separated values"
            )
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
