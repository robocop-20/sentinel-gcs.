"""Short-lived anonymous face-box continuity.

This module uses only face-box geometry and the already anonymous person
ByteTrack ID.  It has no embeddings, identity model, gallery, or reappearance
matching after its small time-to-live window.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import BBox, FaceDetection


@dataclass
class _FaceTrack:
    bbox: BBox
    seen_at: float


def _iou(left: BBox, right: BBox) -> float:
    x1, y1 = max(left.x, right.x), max(left.y, right.y)
    x2 = min(left.x + left.width, right.x + right.width)
    y2 = min(left.y + left.height, right.y + right.height)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union if union > 0 else 0.0


class AnonymousFaceTracker:
    """Assign transient face-box IDs without biometric comparison."""

    def __init__(self, *, ttl_s: float, iou_threshold: float) -> None:
        self.ttl_s = max(ttl_s, 0.1)
        self.iou_threshold = min(max(iou_threshold, 0.0), 1.0)
        self._tracks: dict[str, _FaceTrack] = {}
        self._next_id = 1

    def assign(self, faces: list[FaceDetection], timestamp: float) -> None:
        self._expire(timestamp)
        used: set[str] = set()
        for face in faces:
            # A face inside a confirmed person box inherits the person’s
            # existing anonymous ByteTrack continuity; no face comparison is
            # necessary or performed.
            if face.linked_track_id:
                track_id = f"{face.linked_track_id}-FACE"
            else:
                candidates = [
                    (track_id, _iou(face.bbox, state.bbox))
                    for track_id, state in self._tracks.items()
                    if track_id not in used
                ]
                track_id, overlap = max(
                    candidates, key=lambda item: item[1], default=("", 0.0)
                )
                if overlap < self.iou_threshold:
                    track_id = f"face-observation-{self._next_id:04d}"
                    self._next_id += 1
            face.face_track_id = track_id
            self._tracks[track_id] = _FaceTrack(bbox=face.bbox, seen_at=timestamp)
            used.add(track_id)

    def _expire(self, now: float) -> None:
        self._tracks = {
            track_id: state
            for track_id, state in self._tracks.items()
            if now - state.seen_at <= self.ttl_s
        }
