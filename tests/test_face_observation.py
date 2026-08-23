import numpy as np

from app.face_observation import enrich_face_observations, score_face_quality
from app.schemas import BBox, FaceDetection


def test_face_quality_rejects_uniform_dark_crop():
    face = FaceDetection(confidence=0.9, bbox=BBox(x=10, y=10, width=100, height=100))
    quality = score_face_quality(np.zeros((160, 160, 3), dtype=np.uint8), face, 0.65)
    assert not quality.usable_for_operator_review
    assert "low_sharpness" in quality.issues
    assert "poor_lighting" in quality.issues


def test_face_observation_links_to_anonymous_person_track():
    face = FaceDetection(
        confidence=0.9,
        bbox=BBox(x=30, y=30, width=100, height=100),
        landmarks=[(50, 60), (110, 60), (80, 90)],
    )
    detections = [
        {
            "track_id": "camera-01-T-007",
            "class": "person",
            "bbox": {"x": 0, "y": 0, "width": 200, "height": 300},
        }
    ]
    frame = np.random.default_rng(1).integers(0, 256, (320, 240, 3), dtype=np.uint8)
    enrich_face_observations(frame, [face], detections, 0.65)
    assert face.linked_track_id == "camera-01-T-007"
    assert face.quality is not None
    assert 0 <= face.quality.quality_score <= 1
