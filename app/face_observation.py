"""Privacy-preserving face observation quality and anonymous track linking.

This layer assesses whether a detected face is visually usable for a human
operator's review. It neither creates facial vectors nor compares people.
"""

from __future__ import annotations

import math

import cv2

from .schemas import FaceDetection, FaceQuality


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _face_track_link(face: FaceDetection, detections: list[dict]) -> str | None:
    """Associate a face to the containing anonymous person track in this frame."""
    face_center_x = face.bbox.x + face.bbox.width / 2
    face_center_y = face.bbox.y + face.bbox.height / 2
    candidates: list[tuple[float, str]] = []
    for detection in detections:
        if detection.get("class") != "person":
            continue
        box = detection["bbox"]
        if (
            box["x"] <= face_center_x <= box["x"] + box["width"]
            and box["y"] <= face_center_y <= box["y"] + box["height"]
        ):
            candidates.append((box["width"] * box["height"], detection["track_id"]))
    return min(candidates)[1] if candidates else None


def score_face_quality(frame, face: FaceDetection, minimum_score: float) -> FaceQuality:
    """Calculate transparent image-quality heuristics from the detected face crop."""
    frame_height, frame_width = frame.shape[:2]
    x1, y1 = max(0, int(face.bbox.x)), max(0, int(face.bbox.y))
    x2 = min(frame_width, math.ceil(face.bbox.x + face.bbox.width))
    y2 = min(frame_height, math.ceil(face.bbox.y + face.bbox.height))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return FaceQuality(
            quality_score=0,
            usable_for_operator_review=False,
            sharpness_score=0,
            lighting_score=0,
            size_score=0,
            frontal_score=0,
            issues=["invalid_face_crop"],
        )

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sharpness_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharpness_score = _bounded(sharpness_variance / 120.0)
    brightness = float(gray.mean()) / 255.0
    lighting_score = _bounded(1.0 - abs(brightness - 0.5) / 0.5)
    size_score = _bounded(min(face.bbox.width, face.bbox.height) / 96.0)

    frontal_score = 0.5
    if len(face.landmarks) >= 3:
        left_eye, right_eye, nose = face.landmarks[:3]
        eye_distance = math.dist(left_eye, right_eye)
        if eye_distance > 1:
            eye_mid_x = (left_eye[0] + right_eye[0]) / 2
            nose_offset = abs(nose[0] - eye_mid_x) / eye_distance
            eye_tilt = abs(left_eye[1] - right_eye[1]) / eye_distance
            frontal_score = _bounded(1.0 - 1.25 * (nose_offset + eye_tilt))

    quality_score = _bounded(
        0.40 * sharpness_score
        + 0.25 * lighting_score
        + 0.20 * size_score
        + 0.15 * frontal_score
    )
    issues: list[str] = []
    if min(face.bbox.width, face.bbox.height) < 80:
        issues.append("face_too_small")
    if sharpness_score < 0.5:
        issues.append("low_sharpness")
    if lighting_score < 0.5:
        issues.append("poor_lighting")
    if frontal_score < 0.5:
        issues.append("non_frontal_pose")
    return FaceQuality(
        quality_score=round(quality_score, 4),
        usable_for_operator_review=quality_score >= minimum_score and not issues,
        sharpness_score=round(sharpness_score, 4),
        lighting_score=round(lighting_score, 4),
        size_score=round(size_score, 4),
        frontal_score=round(frontal_score, 4),
        issues=issues,
    )


def enrich_face_observations(
    frame, faces: list[FaceDetection], detections: list[dict], minimum_score: float
) -> None:
    """Add transient quality and anonymous Track-ID correlation to face observations."""
    for face in faces:
        face.linked_track_id = _face_track_link(face, detections)
        face.quality = score_face_quality(frame, face, minimum_score)
