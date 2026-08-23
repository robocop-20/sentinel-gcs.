from app.face_tracking import AnonymousFaceTracker
from app.schemas import BBox, FaceDetection


def _face(x: float, y: float, linked_track_id: str | None = None) -> FaceDetection:
    return FaceDetection(
        confidence=0.9,
        bbox=BBox(x=x, y=y, width=40, height=40),
        linked_track_id=linked_track_id,
    )


def test_linked_face_uses_existing_anonymous_person_track_only():
    tracker = AnonymousFaceTracker(ttl_s=2, iou_threshold=0.25)
    face = _face(10, 10, "camera-01-T-007")
    tracker.assign([face], 1)
    assert face.face_track_id == "camera-01-T-007-FACE"


def test_unlinked_face_keeps_spatial_id_for_overlapping_box():
    tracker = AnonymousFaceTracker(ttl_s=2, iou_threshold=0.25)
    first, second = _face(10, 10), _face(14, 12)
    tracker.assign([first], 1)
    tracker.assign([second], 1.5)
    assert second.face_track_id == first.face_track_id


def test_unlinked_face_is_not_reidentified_after_ttl():
    tracker = AnonymousFaceTracker(ttl_s=1, iou_threshold=0.25)
    first, later = _face(10, 10), _face(10, 10)
    tracker.assign([first], 1)
    tracker.assign([later], 2.1)
    assert later.face_track_id != first.face_track_id
