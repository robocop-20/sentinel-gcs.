"""Track-local confidence smoothing for operator display only.

The YOLO score remains the raw per-frame measurement used by deterministic
rules. This bounded EMA is only for a less distracting live preview/readout.
"""

from __future__ import annotations


class TrackConfidenceSmoother:
    def __init__(self, alpha: float, ttl_s: float) -> None:
        self.alpha = min(max(alpha, 0.01), 1.0)
        self.ttl_s = max(ttl_s, 1.0)
        self._values: dict[str, tuple[float, float]] = {}

    def update(self, track_id: str, raw_confidence: float, observed_at: float) -> float:
        """Return an EWMA score for this active ByteTrack ID."""
        self._expire(observed_at)
        previous = self._values.get(track_id)
        value = (
            raw_confidence
            if previous is None
            else self.alpha * raw_confidence + (1 - self.alpha) * previous[0]
        )
        self._values[track_id] = (value, observed_at)
        return round(value, 6)

    def _expire(self, now: float) -> None:
        stale = [
            track_id
            for track_id, (_, seen_at) in self._values.items()
            if now - seen_at > self.ttl_s
        ]
        for track_id in stale:
            del self._values[track_id]
