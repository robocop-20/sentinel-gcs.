"""Low-latency image-plane movement estimates for anonymous ByteTrack IDs.

Pixel velocity is intentionally labelled as image-plane velocity: it is not a
ground speed until calibrated GPS/IMU/camera geometry is available.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot


@dataclass
class _PreviousTrack:
    center_x: float
    center_y: float
    timestamp: float
    speed_px_s: float | None = None


class TrackMotionEstimator:
    def __init__(
        self,
        *,
        moving_threshold_px_s: float,
        ttl_s: float,
        smoothing_alpha: float = 0.35,
    ) -> None:
        self.moving_threshold_px_s = moving_threshold_px_s
        self.ttl_s = ttl_s
        self.smoothing_alpha = smoothing_alpha
        self._previous: dict[str, _PreviousTrack] = {}

    def _expire(self, timestamp: float) -> None:
        self._previous = {
            track_id: sample
            for track_id, sample in self._previous.items()
            if timestamp - sample.timestamp <= self.ttl_s
        }

    def observe(
        self,
        track_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        timestamp: float,
    ) -> dict:
        self._expire(timestamp)
        center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
        previous = self._previous.get(track_id)
        self._previous[track_id] = _PreviousTrack(center_x, center_y, timestamp)
        if previous is None or timestamp <= previous.timestamp:
            return {
                "status": "unknown",
                "speed_image_px_s": None,
                "image_heading_deg": None,
            }

        elapsed_s = timestamp - previous.timestamp
        if elapsed_s > self.ttl_s:
            return {
                "status": "unknown",
                "speed_image_px_s": None,
                "image_heading_deg": None,
            }
        delta_x, delta_y = center_x - previous.center_x, center_y - previous.center_y
        raw_speed = hypot(delta_x, delta_y) / elapsed_s
        speed = (
            raw_speed
            if previous.speed_px_s is None
            else (
                self.smoothing_alpha * raw_speed
                + (1 - self.smoothing_alpha) * previous.speed_px_s
            )
        )
        self._previous[track_id] = _PreviousTrack(center_x, center_y, timestamp, speed)
        # 0° is image-up; this is an image-plane direction, not compass heading.
        heading = (degrees(atan2(delta_x, -delta_y)) + 360) % 360 if raw_speed else None
        return {
            "status": "moving" if speed >= self.moving_threshold_px_s else "stationary",
            "speed_image_px_s": round(speed, 2),
            "image_heading_deg": None if heading is None else round(heading, 1),
        }
