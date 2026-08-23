"""Local pose-and-time fall observation for anonymous person tracks.

This module uses only the current track ID and COCO body keypoints.  It does
not create body embeddings, identify a person, or retain a biometric template.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from math import atan2, degrees
from typing import Iterable

from .schemas import FallObservation


LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12


@dataclass(frozen=True)
class _PoseSample:
    timestamp: float
    score: float
    torso_angle_deg: float
    aspect_ratio: float


def _midpoint(
    points: list[tuple[float, float, float]],
    first: int,
    second: int,
    minimum_confidence: float,
) -> tuple[float, float] | None:
    if len(points) <= second:
        return None
    left, right = points[first], points[second]
    if (
        len(left) < 3
        or len(right) < 3
        or left[2] < minimum_confidence
        or right[2] < minimum_confidence
    ):
        return None
    return ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)


class PoseFallDetector:
    """Require sustained horizontal torso posture before emitting one alert."""

    def __init__(
        self,
        *,
        keypoint_confidence: float,
        minimum_score: float,
        minimum_frames: int,
        window_s: float,
        cooldown_s: float,
    ) -> None:
        self.keypoint_confidence = keypoint_confidence
        self.minimum_score = minimum_score
        self.minimum_frames = max(minimum_frames, 2)
        self.window_s = max(window_s, 0.5)
        self.cooldown_s = max(cooldown_s, 1.0)
        self._history: dict[str, deque[_PoseSample]] = defaultdict(deque)
        self._last_emitted: dict[str, float] = {}

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    def observe(
        self,
        track_id: str,
        *,
        bbox_width: float,
        bbox_height: float,
        keypoints: Iterable[Iterable[float]],
        timestamp: float,
    ) -> FallObservation | None:
        """Observe one pose vector and return a confirmed, rate-limited fall signal."""
        points = [tuple(float(value) for value in point) for point in keypoints]
        shoulders = _midpoint(
            points, LEFT_SHOULDER, RIGHT_SHOULDER, self.keypoint_confidence
        )
        hips = _midpoint(points, LEFT_HIP, RIGHT_HIP, self.keypoint_confidence)
        if shoulders is None or hips is None or bbox_height <= 0:
            return None

        dx, dy = hips[0] - shoulders[0], hips[1] - shoulders[1]
        # 0 degrees is upright; 90 degrees is horizontal. This is a skeletal
        # geometry feature, not an identity descriptor.
        torso_angle = min(90.0, abs(degrees(atan2(abs(dx), max(abs(dy), 1e-6)))))
        aspect_ratio = max(bbox_width, 0.0) / bbox_height
        horizontal_score = self._clamp((torso_angle - 35.0) / 45.0)
        aspect_score = self._clamp((aspect_ratio - 0.40) / 0.60)
        score = 0.70 * horizontal_score + 0.30 * aspect_score
        history = self._history[track_id]
        history.append(_PoseSample(timestamp, score, torso_angle, aspect_ratio))
        while history and timestamp - history[0].timestamp > self.window_s:
            history.popleft()
        for stale_track in [
            key
            for key, samples in self._history.items()
            if not samples or timestamp - samples[-1].timestamp > self.window_s * 2
        ]:
            del self._history[stale_track]

        supporting = [
            sample for sample in history if sample.score >= self.minimum_score
        ]
        if len(supporting) < self.minimum_frames:
            return None
        if (
            timestamp - self._last_emitted.get(track_id, float("-inf"))
            < self.cooldown_s
        ):
            return None
        confidence = sum(sample.score for sample in supporting) / len(supporting)
        self._last_emitted[track_id] = timestamp
        latest = supporting[-1]
        return FallObservation(
            track_id=track_id,
            timestamp=timestamp,
            confidence=round(confidence, 4),
            torso_angle_deg=round(latest.torso_angle_deg, 2),
            bbox_aspect_ratio=round(latest.aspect_ratio, 3),
            sustained_frames=len(supporting),
        )
