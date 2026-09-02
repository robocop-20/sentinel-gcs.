"""Live OpenCV -> YOLO11 -> ByteTrack perception adapter.

The worker never queues old frames: capture, inference, and API delivery each
retain only their newest item. This keeps the system real-time when hardware
cannot infer every camera frame.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from collections import deque
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import cv2
from ultralytics import YOLO

from .confidence import TrackConfidenceSmoother
from .config import get_settings
from .evidence_store import EvidenceStore
from .fall_detection import PoseFallDetector
from .motion import TrackMotionEstimator
from .model_release import ModelRelease, verify_model_release
from .observability import configure_logging
from .service_health import ServiceHealth
from .track_gate import TrackConfirmationGate
from .vision_runtime import LatestApiPublisher, LatestFrameCapture


LOGGER = logging.getLogger(__name__)


# COCO class emitted by YOLO -> normalized domain class stored by Sentinel.
COCO_CATEGORY = {
    "person": "person",
    "boat": "vessel",
    "vessel": "vessel",
    "small_boat": "vessel",
    "cargo_vessel": "vessel",
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "motorcycle": "vehicle",
    "vehicle": "vehicle",
    "container": "container",
    "shipping_container": "container",
    "shipping container": "container",
}

# COCO-17 skeleton segments. They are used only to draw the current local
# pose vector on the preview; no keypoints leave the vision worker.
POSE_EDGES = (
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
)


def capture_source(settings):
    source = (
        int(settings.video_source)
        if settings.video_source.isdigit()
        else settings.video_source
    )
    backends = {"dshow": cv2.CAP_DSHOW, "gstreamer": cv2.CAP_GSTREAMER}
    capture = cv2.VideoCapture(
        source, backends.get(settings.video_backend.lower(), cv2.CAP_ANY)
    )
    # An IP camera can buffer several stale MJPEG frames.  The pipeline only
    # needs the most recent one, so ask OpenCV to retain a single frame where
    # the active backend supports it.  Failure is harmless on backends that
    # do not expose CAP_PROP_BUFFERSIZE.
    try:
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except cv2.error:
        pass
    return capture


def orient_frame(frame, degrees: int):
    """Return a camera frame in the configured physical mounting orientation."""
    transforms = {
        0: lambda value: value,
        90: lambda value: cv2.rotate(value, cv2.ROTATE_90_CLOCKWISE),
        180: lambda value: cv2.rotate(value, cv2.ROTATE_180),
        270: lambda value: cv2.rotate(value, cv2.ROTATE_90_COUNTERCLOCKWISE),
    }
    try:
        return transforms[int(degrees)](frame)
    except KeyError as exc:
        raise ValueError("VIDEO_ROTATION_DEG must be one of 0, 90, 180, 270") from exc


def configure_runtime(settings) -> None:
    """Bound CPU thread use when requested; GPUs remain selected by YOLO_DEVICE."""
    if settings.vision_cpu_threads <= 0:
        return
    try:
        import torch

        torch.set_num_threads(settings.vision_cpu_threads)
    except ImportError:
        LOGGER.debug("Torch is unavailable; CPU thread limit was not applied")


def target_class_ids(model: YOLO, accepted_names: set[str]) -> list[int]:
    names = (
        model.names.items() if isinstance(model.names, dict) else enumerate(model.names)
    )
    ids = [index for index, name in names if str(name).lower() in accepted_names]
    if not ids:
        raise ValueError(
            f"No configured target classes exist in the model: {sorted(accepted_names)}"
        )
    return ids


def _iou(first: dict, second: list[float]) -> float:
    """Intersection over union for matching a pose box to a confirmed person."""
    left = max(float(first["x"]), float(second[0]))
    top = max(float(first["y"]), float(second[1]))
    right = min(float(first["x"] + first["width"]), float(second[2]))
    bottom = min(float(first["y"] + first["height"]), float(second[3]))
    overlap = max(0.0, right - left) * max(0.0, bottom - top)
    if overlap <= 0:
        return 0.0
    first_area = float(first["width"]) * float(first["height"])
    second_area = max(0.0, float(second[2] - second[0])) * max(
        0.0, float(second[3] - second[1])
    )
    return overlap / max(first_area + second_area - overlap, 1e-6)


def _pose_vectors_for_people(
    pose_result, people: list[dict]
) -> dict[str, list[list[float]]]:
    """Map pose keypoint vectors to already-confirmed anonymous person tracks."""
    if pose_result.boxes is None or pose_result.keypoints is None:
        return {}
    try:
        boxes = pose_result.boxes.xyxy.cpu().tolist()
        vectors = pose_result.keypoints.data.cpu().tolist()
    except (AttributeError, TypeError):
        return {}
    matched: dict[str, list[list[float]]] = {}
    for person in people:
        candidates = [
            (_iou(person["bbox"], box), vector) for box, vector in zip(boxes, vectors)
        ]
        if candidates:
            score, vector = max(candidates, key=lambda item: item[0])
            if score >= 0.30:
                matched[str(person["track_id"])] = vector
    return matched


def _recent_inference_fps(
    timestamps: deque[float], now: float, window_s: float = 5.0
) -> float:
    """Measure recent throughput so recovery is not diluted by old downtime."""
    cutoff = now - max(window_s, 1.0)
    while timestamps and timestamps[0] < cutoff:
        timestamps.popleft()
    if len(timestamps) < 2:
        return 0.0
    return (len(timestamps) - 1) / max(timestamps[-1] - timestamps[0], 0.001)


def build_metrics(
    settings,
    capture,
    publisher,
    *,
    frames_inferred: int,
    inference_fps: float,
    last_inference_ms: float | None,
    last_end_to_end_ms: float | None,
    last_detection_count: int,
    status: str,
    last_error: str | None,
    model_release: ModelRelease,
    fall_pose_model_loaded: bool = False,
    fall_observations: int = 0,
    fall_last_error: str | None = None,
    face_detector_loaded: bool = False,
    face_last_error: str | None = None,
    person_verifier_loaded: bool = False,
    detections_rejected_low_confidence: int = 0,
    detections_rejected_temporal: int = 0,
    detections_rejected_person_verifier: int = 0,
) -> dict:
    capture_stats = capture.metrics()
    publisher_stats = publisher.metrics()
    errors = [
        value
        for value in (
            last_error,
            capture_stats["last_error"],
            publisher_stats["last_error"],
        )
        if value
    ]
    return {
        "source": settings.camera_id,
        "timestamp": time.time(),
        "status": "degraded" if errors else status,
        "model_name": settings.yolo_model,
        "device": settings.yolo_device or "auto",
        "frames_captured": capture_stats["frames_captured"],
        "frames_inferred": frames_inferred,
        "frames_posted": publisher_stats["frames_posted"],
        "frames_dropped_for_latency": capture_stats["frames_replaced"]
        + publisher_stats["frames_replaced"],
        "capture_fps": round(float(capture_stats["capture_fps"]), 2),
        "inference_fps": round(max(inference_fps, 0.0), 2),
        "last_inference_ms": None
        if last_inference_ms is None
        else round(last_inference_ms, 2),
        "last_end_to_end_ms": None
        if last_end_to_end_ms is None
        else round(last_end_to_end_ms, 2),
        "last_detection_count": last_detection_count,
        "detections_rejected_low_confidence": detections_rejected_low_confidence,
        "detections_rejected_temporal": detections_rejected_temporal,
        "detections_rejected_person_verifier": detections_rejected_person_verifier,
        "person_verifier_enabled": settings.enable_person_verifier,
        "person_verifier_loaded": person_verifier_loaded,
        "face_detection_enabled": settings.enable_face_detection,
        "face_detector_loaded": face_detector_loaded,
        "face_last_error": face_last_error,
        "fall_detection_enabled": settings.enable_fall_detection,
        "fall_pose_model_loaded": fall_pose_model_loaded,
        "fall_observations": fall_observations,
        "fall_last_error": fall_last_error,
        "model_release": f"{model_release.release_name}:{model_release.version}",
        "model_integrity_verified": model_release.verified,
        "last_error": " | ".join(errors)[:500] if errors else None,
    }


def annotated_preview(
    frame,
    detections: list[dict],
    faces: list,
    *,
    max_dimension_px: int,
    jpeg_quality: int,
    pose_vectors: dict[str, list[list[float]]] | None = None,
) -> bytes | None:
    """Render the post-inference monitoring image at a capped rate."""
    scale = min(1.0, max(max_dimension_px, 32) / max(frame.shape[:2]))
    if scale < 1.0:
        preview = cv2.resize(
            frame,
            (
                max(1, round(frame.shape[1] * scale)),
                max(1, round(frame.shape[0] * scale)),
            ),
            interpolation=cv2.INTER_AREA,
        )
    else:
        preview = frame.copy()
    # A portrait mobile feed is narrow.  Multi-line diagnostic panels used to
    # stack at y=0 for overlapping detections and hide the actual camera
    # image.  Keep the on-image label short; full verification details remain
    # available in the track inspector.
    label_scale = max(0.42, min(0.62, preview.shape[1] / 1200))
    label_rects: list[tuple[int, int, int, int]] = []

    def place_label(x: int, y1: int, y2: int, width: int, height: int) -> tuple[int, int]:
        """Place labels near their boxes without covering one another."""
        left = max(3, min(x, max(3, preview.shape[1] - width - 3)))
        preferred = (y1 - height - 4, y2 + 4, y1 + 3)
        for top in preferred:
            top = max(3, min(top, max(3, preview.shape[0] - height - 3)))
            candidate = (left, top, left + width, top + height)
            overlaps = any(
                candidate[0] < other[2]
                and candidate[2] > other[0]
                and candidate[1] < other[3]
                and candidate[3] > other[1]
                for other in label_rects
            )
            if not overlaps:
                label_rects.append(candidate)
                return left, top
        # Dense scenes can still overlap. Find the nearest free horizontal row
        # rather than obscuring the image with an expanding panel.
        for top in range(3, max(4, preview.shape[0] - height), height + 3):
            candidate = (left, top, left + width, top + height)
            if not any(
                candidate[0] < other[2]
                and candidate[2] > other[0]
                and candidate[1] < other[3]
                and candidate[3] > other[1]
                for other in label_rects
            ):
                label_rects.append(candidate)
                return left, top
        return left, max(3, min(y1 + 3, preview.shape[0] - height - 3))

    for detection in detections:
        bbox = detection["bbox"]
        x1, y1 = round(bbox["x"] * scale), round(bbox["y"] * scale)
        x2, y2 = (
            round((bbox["x"] + bbox["width"]) * scale),
            round((bbox["y"] + bbox["height"]) * scale),
        )
        class_name = detection["class"].upper()
        colour = (63, 218, 194) if class_name == "PERSON" else (76, 180, 255)
        fall = detection.get("fall")
        if fall:
            colour = (48, 74, 255)
        cv2.rectangle(preview, (x1, y1), (x2, y2), colour, 3)
        vector = (pose_vectors or {}).get(detection["track_id"])
        if vector:
            points: dict[int, tuple[int, int]] = {}
            for index, keypoint in enumerate(vector):
                if len(keypoint) >= 3 and keypoint[2] >= 0.45:
                    points[index] = (
                        round(keypoint[0] * scale),
                        round(keypoint[1] * scale),
                    )
            for first, second in POSE_EDGES:
                if first in points and second in points:
                    cv2.line(
                        preview,
                        points[first],
                        points[second],
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )
            for point in points.values():
                cv2.circle(preview, point, 3, (255, 255, 255), -1, cv2.LINE_AA)
        display_confidence = detection.get(
            "display_confidence", detection["confidence"]
        )
        short_track_id = str(detection["track_id"]).replace(
            f"{detection['track_id'].split('-T-')[0]}-", ""
        )
        label = f"{class_name} {display_confidence * 100:.0f}% | {short_track_id}"
        verification = detection.get("person_verification") or {}
        verdict = verification.get("verdict")
        if verdict == "confirmed":
            label += " | CHECK"
        if fall:
            label += " | FALL"
        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, label_scale, 1)[0]
        panel_width, panel_height = label_size[0] + 12, label_size[1] + 10
        panel_left, panel_top = place_label(x1, y1, y2, panel_width, panel_height)
        cv2.rectangle(
            preview,
            (panel_left, panel_top),
            (panel_left + panel_width, panel_top + panel_height),
            (8, 20, 26),
            -1,
        )
        cv2.rectangle(
            preview,
            (panel_left, panel_top),
            (panel_left + panel_width, panel_top + panel_height),
            colour,
            1,
        )
        cv2.putText(
            preview,
            label,
            (panel_left + 6, panel_top + label_size[1] + 4),
            cv2.FONT_HERSHEY_DUPLEX,
            label_scale,
            colour,
            1,
            cv2.LINE_AA,
        )
    for face in faces:
        x1, y1 = round(face.bbox.x * scale), round(face.bbox.y * scale)
        x2 = round((face.bbox.x + face.bbox.width) * scale)
        y2 = round((face.bbox.y + face.bbox.height) * scale)
        colour = (229, 87, 255)
        cv2.rectangle(preview, (x1, y1), (x2, y2), colour, 2)
        label = f"FACE {face.confidence * 100:.0f}%"
        text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, label_scale, 1)[0]
        label_width, label_height = text_size[0] + 10, text_size[1] + 8
        label_left, label_top = place_label(x1, y1, y2, label_width, label_height)
        cv2.rectangle(
            preview,
            (label_left, label_top),
            (label_left + label_width, label_top + label_height),
            (22, 8, 26),
            -1,
        )
        cv2.putText(
            preview,
            label,
            (label_left + 5, label_top + text_size[1] + 3),
            cv2.FONT_HERSHEY_DUPLEX,
            label_scale,
            colour,
            1,
            cv2.LINE_AA,
        )
    ok, encoded = cv2.imencode(
        ".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, min(max(jpeg_quality, 1), 100)]
    )
    return encoded.tobytes() if ok else None


def main() -> None:
    settings = get_settings()
    settings.validate()
    configure_logging("sentinel-vision", settings.log_level)
    health = ServiceHealth("sentinel-vision", settings.service_health_port)
    health.start()
    api_url = os.getenv("API_URL", "http://localhost:8080")
    if not settings.video_source:
        raise SystemExit(
            "VIDEO_SOURCE is required; USB indices need VIDEO_BACKEND=dshow on Windows."
        )

    configure_runtime(settings)
    model = YOLO(settings.yolo_model)
    class_ids = target_class_ids(model, settings.target_classes)
    model_release = verify_model_release(
        settings.yolo_model,
        settings.model_manifest_path,
        required=settings.require_model_manifest,
        expected_classes=settings.release_expected_classes,
    )
    if model_release.verified:
        model_names = (
            model.names.values() if isinstance(model.names, dict) else model.names
        )
        missing_runtime_classes = set(model_release.classes).difference(
            {str(name).lower() for name in model_names}
        )
        if missing_runtime_classes:
            raise SystemExit(
                f"Model weights do not expose manifest classes: {sorted(missing_runtime_classes)}"
            )
    LOGGER.info(
        "Vision model loaded",
        extra={"event": "model_loaded", "component": "object_detection"},
    )
    face_detector = None
    face_tracker = None
    blur_faces = None
    person_verifier = None
    face_last_error: str | None = None
    if settings.enable_face_detection:
        # Optional and isolated from the live object-tracking path.
        try:
            from .face_detector import FaceDetector, blur_faces as face_blur
            from .face_tracking import AnonymousFaceTracker

            face_detector = FaceDetector(
                settings.face_detector_model_path,
                settings.face_detection_confidence,
                settings.face_detection_max_dimension_px,
            )
            face_tracker = AnonymousFaceTracker(
                ttl_s=settings.face_track_ttl_s,
                iou_threshold=settings.face_track_iou_threshold,
            )
            blur_faces = face_blur
        except Exception as exc:
            # Face observation is optional and must never take down object
            # detection, tracking, local rules, or the camera reconnect loop.
            face_last_error = f"{type(exc).__name__}: {exc}"[:300]
            LOGGER.warning(
                "Face observation unavailable",
                extra={
                    "event": "optional_model_unavailable",
                    "component": "face_observation",
                },
            )
    if settings.enable_person_verifier:
        from .person_verifier import LocalPersonVerifier

        person_verifier = LocalPersonVerifier(settings)
    pose_model = None
    fall_detector = None
    if settings.enable_fall_detection:
        pose_path = Path(settings.fall_pose_model_path)
        if pose_path.is_file():
            pose_model = YOLO(str(pose_path))
            fall_detector = PoseFallDetector(
                keypoint_confidence=settings.fall_pose_confidence,
                minimum_score=settings.fall_min_confidence,
                minimum_frames=settings.fall_min_sustained_frames,
                window_s=settings.fall_confirmation_window_s,
                cooldown_s=settings.fall_event_cooldown_s,
            )
            LOGGER.info(
                "Local pose model loaded",
                extra={"event": "model_loaded", "component": "fall_pose"},
            )
        else:
            LOGGER.warning(
                "Configured pose model is unavailable",
                extra={"event": "optional_model_unavailable", "component": "fall_pose"},
            )
    evidence_store = EvidenceStore(
        enabled=settings.enable_evidence_capture,
        directory=settings.evidence_dir,
        interval_s=settings.evidence_capture_interval_s,
        max_dimension_px=settings.evidence_max_dimension_px,
        jpeg_quality=settings.evidence_jpeg_quality,
        encryption_key_file=settings.evidence_encryption_key_file,
    )
    confidence_smoother = TrackConfidenceSmoother(
        settings.confidence_display_ema_alpha, settings.confidence_track_ttl_s
    )
    motion_estimator = TrackMotionEstimator(
        moving_threshold_px_s=settings.motion_moving_threshold_px_s,
        ttl_s=settings.motion_track_ttl_s,
    )
    confirmation_gate = TrackConfirmationGate(
        minimum_observations=settings.min_track_confirmation_frames,
        maximum_gap_s=settings.track_confirmation_max_gap_s,
        evidence_window=settings.track_evidence_window,
        minimum_class_stability=settings.track_min_class_stability,
    )

    capture = LatestFrameCapture(
        lambda: capture_source(settings),
        settings.vision_reconnect_delay_s,
        settings.vision_reconnect_max_delay_s,
    )
    publisher = LatestApiPublisher(
        api_url,
        settings.vision_api_timeout_s,
        settings.service_client_id,
        settings.service_client_secret_file,
        settings.service_ca_cert,
        settings.service_client_cert,
        settings.service_client_key,
    )
    capture.start()
    publisher.start()
    last_sequence = 0
    input_frame_count = 0
    frames_inferred = 0
    inference_timestamps: deque[float] = deque()
    last_inference_ms: float | None = None
    last_end_to_end_ms: float | None = None
    last_detection_count = 0
    last_error: str | None = None
    rejected_low_confidence = 0
    rejected_temporal = 0
    rejected_person_verifier = 0
    fall_observations = 0
    fall_last_error: str | None = None
    next_metrics_at = 0.0
    next_preview_at = 0.0
    last_successful_frame_at = 0.0
    # The face detector is intentionally lower-rate than primary perception.
    # Keep only a very short-lived local display cache so a privacy-blurred
    # preview remains smooth between face-observation passes.
    latest_faces: list = []
    latest_faces_at = 0.0

    try:
        while True:
            captured = capture.next_after(last_sequence)
            now = time.monotonic()
            if captured is None:
                if not last_successful_frame_at or now - last_successful_frame_at > max(
                    settings.vision_status_interval_s * 2, 5.0
                ):
                    health.set_ready(
                        False, reason="waiting_for_frames", model_loaded=True
                    )
                if now >= next_metrics_at:
                    publisher.submit_metrics(
                        build_metrics(
                            settings,
                            capture,
                            publisher,
                            frames_inferred=frames_inferred,
                            inference_fps=_recent_inference_fps(
                                inference_timestamps, now
                            ),
                            last_inference_ms=last_inference_ms,
                            last_end_to_end_ms=last_end_to_end_ms,
                            last_detection_count=last_detection_count,
                            status="waiting_for_frames",
                            last_error=last_error,
                            model_release=model_release,
                            fall_pose_model_loaded=pose_model is not None,
                            fall_observations=fall_observations,
                            fall_last_error=fall_last_error,
                            face_detector_loaded=face_detector is not None,
                            face_last_error=face_last_error,
                            person_verifier_loaded=bool(
                                person_verifier and person_verifier.available
                            ),
                            detections_rejected_low_confidence=rejected_low_confidence,
                            detections_rejected_temporal=rejected_temporal,
                            detections_rejected_person_verifier=rejected_person_verifier,
                        )
                    )
                    next_metrics_at = now + settings.vision_status_interval_s
                continue
            last_sequence = captured.sequence
            input_frame_count += 1
            if input_frame_count % max(settings.frame_interval, 1):
                continue
            # Orient once at the boundary. Every model and emitted bounding
            # box below intentionally uses this same frame coordinate system.
            frame = orient_frame(captured.frame, settings.video_rotation_deg)

            infer_started_at = time.perf_counter()
            track_options = {
                "persist": True,
                "tracker": settings.tracker_config,
                "conf": settings.minimum_candidate_confidence,
                "imgsz": settings.vision_img_size,
                "max_det": settings.vision_max_detections,
                "classes": class_ids,
                "verbose": False,
            }
            if settings.yolo_device:
                track_options["device"] = settings.yolo_device
            try:
                result = model.track(frame, **track_options)[0]
            except Exception as exc:
                last_error = f"YOLO inference failed: {type(exc).__name__}: {exc}"
                health.set_ready(
                    False, reason="inference_failed", error_type=type(exc).__name__
                )
                LOGGER.exception(
                    "YOLO inference failed",
                    extra={
                        "event": "inference_failed",
                        "component": "object_detection",
                    },
                )
                continue

            last_inference_ms = (time.perf_counter() - infer_started_at) * 1000
            frames_inferred += 1
            inference_timestamps.append(time.monotonic())
            detections: list[dict] = []
            if result.boxes is not None:
                for box in result.boxes:
                    # Persistent ByteTrack IDs are essential; an unassociated
                    # first-frame box is deliberately not emitted as a track.
                    if box.id is None:
                        continue
                    model_class = str(result.names[int(box.cls.item())]).lower()
                    object_class = COCO_CATEGORY.get(model_class, model_class)
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    track_id = f"{settings.camera_id}-T-{int(box.id.item()):03d}"
                    raw_confidence = round(float(box.conf.item()), 6)
                    if raw_confidence < settings.candidate_confidence_for(object_class):
                        rejected_low_confidence += 1
                        continue
                    # Do not show, store, score, or emit weak person claims.
                    # ByteTrack still receives the candidate internally, so a
                    # later strong observation can retain its anonymous ID.
                    if raw_confidence < settings.publish_confidence_for(object_class):
                        rejected_low_confidence += 1
                        continue
                    confirmed, observation_count = confirmation_gate.observe(
                        track_id,
                        captured.captured_at,
                        class_name=object_class,
                        confidence=raw_confidence,
                        minimum_mean_confidence=settings.track_mean_confidence_for(
                            object_class
                        ),
                        minimum_observations=settings.confirmation_frames_for(
                            object_class
                        ),
                    )
                    track_evidence = confirmation_gate.evidence(track_id)
                    if not confirmed:
                        rejected_temporal += 1
                        continue
                    person_verification = None
                    if (
                        object_class == "person"
                        and person_verifier is not None
                        and person_verifier.should_review(raw_confidence)
                    ):
                        review = person_verifier.verify(
                            track_id,
                            frame,
                            (x1, y1, x2, y2),
                            captured.captured_at,
                        )
                        person_verification = {
                            "method": person_verifier.method,
                            "verdict": review.verdict,
                            "confidence": review.confidence,
                            "iou": review.iou,
                        }
                        # Do not publish a marginal person claim that an
                        # independent local detector contradicts. If the
                        # verifier is unavailable, preserve primary YOLO
                        # availability and make no new claim about it.
                        if review.verdict == "contradicted":
                            rejected_person_verifier += 1
                            continue
                    motion = motion_estimator.observe(
                        track_id, x1, y1, x2, y2, captured.captured_at
                    )
                    # Evidence capture is immutable and strictly non-person.
                    # The API receives only integrity/provenance metadata plus
                    # a local encrypted path; no pixels are placed in events.
                    evidence = (
                        None
                        if object_class == "person"
                        else evidence_store.store(
                            track_id,
                            frame,
                            (x1, y1, x2, y2),
                            captured.captured_at,
                        )
                    )
                    detections.append(
                        {
                            "track_id": track_id,
                            "class": object_class,
                            "model_class": model_class,
                            "confidence": raw_confidence,
                            "display_confidence": confidence_smoother.update(
                                track_id, raw_confidence, captured.captured_at
                            ),
                            "bbox": {
                                "x": x1,
                                "y": y1,
                                "width": x2 - x1,
                                "height": y2 - y1,
                            },
                            "motion": motion,
                            "confirmed_track_observations": observation_count,
                            "track_mean_confidence": track_evidence["mean_confidence"],
                            "track_class_stability": track_evidence["class_stability"],
                            "person_verification": person_verification,
                            # A local preview can blur faces.  Do not persist a
                            # person crop for LLM review or export at all.
                            "evidence_ref": evidence.path if evidence else None,
                            "evidence": evidence.model_dump() if evidence else None,
                        }
                    )
            # Pose runs only for confirmed anonymous person tracks, at a
            # bounded cadence. It is an independent local safety signal and
            # never changes YOLO class, ByteTrack ID, or person confidence.
            pose_vectors: dict[str, list[list[float]]] = {}
            people = [
                detection for detection in detections if detection["class"] == "person"
            ]
            if (
                pose_model is not None
                and fall_detector is not None
                and people
                and frames_inferred % max(settings.fall_pose_interval, 1) == 0
            ):
                pose_options = {
                    "imgsz": settings.fall_pose_img_size,
                    "conf": settings.fall_pose_confidence,
                    "classes": [0],
                    "verbose": False,
                }
                if settings.yolo_device:
                    pose_options["device"] = settings.yolo_device
                try:
                    pose_result = pose_model.predict(frame, **pose_options)[0]
                    fall_last_error = None
                    pose_vectors = _pose_vectors_for_people(pose_result, people)
                    for person in people:
                        vector = pose_vectors.get(person["track_id"])
                        if vector is None:
                            continue
                        bbox = person["bbox"]
                        fall = fall_detector.observe(
                            person["track_id"],
                            bbox_width=bbox["width"],
                            bbox_height=bbox["height"],
                            keypoints=vector,
                            timestamp=captured.captured_at,
                        )
                        if fall is not None:
                            person["fall"] = fall.model_dump()
                            fall_observations += 1
                except Exception as exc:
                    # A secondary safety model must not interrupt perception.
                    fall_last_error = f"{type(exc).__name__}: {exc}"[:300]
                    LOGGER.warning(
                        "Fall pose observation unavailable",
                        extra={
                            "event": "optional_model_unavailable",
                            "component": "fall_pose",
                        },
                    )
            should_preview = (
                settings.enable_annotated_preview and now >= next_preview_at
            )
            faces = []
            preview_faces = []
            # Face observation is a separate, local awareness layer.  It must
            # remain available when a nearby subject fills the frame: generic
            # COCO "person" detection legitimately needs more body context in
            # that case, while the face detector can still report an anonymous
            # face observation.  This never promotes a face into a person
            # track, creates identity data, or changes YOLO/ByteTrack output.
            # It is deliberately bounded to its own cadence.  Primary YOLO +
            # ByteTrack must not wait on a secondary face model for every
            # display refresh.
            run_face_observation = bool(
                face_detector is not None
                and frames_inferred % max(settings.face_detection_interval, 1) == 0
            )
            if run_face_observation:
                try:
                    faces = face_detector.detect(frame)
                    if faces:
                        from .face_observation import enrich_face_observations

                        enrich_face_observations(
                            frame,
                            faces,
                            detections,
                            settings.face_quality_min_score,
                        )
                        face_tracker.assign(faces, captured.captured_at)
                    latest_faces = faces
                    latest_faces_at = now
                    face_last_error = None
                except Exception as exc:
                    face_last_error = f"{type(exc).__name__}: {exc}"[:300]
                    faces = []
                    latest_faces = []
                    latest_faces_at = now

            # Reuse a sub-second local observation only for the visual
            # preview.  It is not emitted as a new face event or used for
            # tracking, identity, or decision-making.
            if latest_faces and now - latest_faces_at <= 0.45:
                preview_faces = latest_faces

            last_detection_count = len(detections)
            last_end_to_end_ms = (time.time() - captured.captured_at) * 1000
            last_error = None
            last_successful_frame_at = now
            health.set_ready(
                True,
                status="processing",
                model_loaded=True,
                frames_inferred=frames_inferred,
            )
            publisher.submit_detections(
                {
                    "batch_id": str(
                        uuid5(
                            NAMESPACE_URL,
                            f"sentinel:{settings.camera_id}:{captured.sequence}:"
                            f"{captured.captured_at:.9f}",
                        )
                    ),
                    "timestamp": captured.captured_at,
                    "captured_at": captured.captured_at,
                    "source": settings.camera_id,
                    "vehicle_id": settings.camera_vehicle_id,
                    "frame_width": frame.shape[1],
                    "frame_height": frame.shape[0],
                    "model_name": settings.yolo_model,
                    "model_version": model_release.version,
                    "model_sha256": model_release.sha256,
                    "model_integrity_verified": model_release.verified,
                    "inference_ms": last_inference_ms,
                    "detections": detections,
                    "faces": [face.model_dump() for face in faces],
                }
            )
            # Preview uses the already-inferred frame, has its own one-frame
            # queue, and never opens a desktop window or delays tracking.
            if should_preview:
                preview_frame = frame.copy()
                if (
                    preview_faces
                    and settings.privacy_blur_faces
                    and blur_faces is not None
                ):
                    blur_faces(preview_frame, preview_faces)
                preview = annotated_preview(
                    preview_frame,
                    detections,
                    preview_faces,
                    max_dimension_px=settings.preview_max_dimension_px,
                    jpeg_quality=settings.preview_jpeg_quality,
                    pose_vectors=pose_vectors,
                )
                if preview:
                    publisher.submit_preview(
                        {
                            "source": settings.camera_id,
                            "timestamp": captured.captured_at,
                            "jpeg_base64": base64.b64encode(preview).decode("ascii"),
                        }
                    )
                next_preview_at = now + 1 / max(settings.preview_fps, 0.2)
            if now >= next_metrics_at:
                publisher.submit_metrics(
                    build_metrics(
                        settings,
                        capture,
                        publisher,
                        frames_inferred=frames_inferred,
                        inference_fps=_recent_inference_fps(inference_timestamps, now),
                        last_inference_ms=last_inference_ms,
                        last_end_to_end_ms=last_end_to_end_ms,
                        last_detection_count=last_detection_count,
                        status="processing",
                        last_error=last_error,
                        model_release=model_release,
                        fall_pose_model_loaded=pose_model is not None,
                        fall_observations=fall_observations,
                        fall_last_error=fall_last_error,
                        face_detector_loaded=face_detector is not None,
                        face_last_error=face_last_error,
                        person_verifier_loaded=bool(
                            person_verifier and person_verifier.available
                        ),
                        detections_rejected_low_confidence=rejected_low_confidence,
                        detections_rejected_temporal=rejected_temporal,
                        detections_rejected_person_verifier=rejected_person_verifier,
                    )
                )
                next_metrics_at = now + settings.vision_status_interval_s
    finally:
        capture.stop()
        publisher.stop()
        health.stop()


if __name__ == "__main__":
    main()
