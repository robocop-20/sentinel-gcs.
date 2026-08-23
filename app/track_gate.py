"""Temporal confirmation gate for ByteTrack observations.

The gate reduces one-frame false positives before a detection is emitted to the
backend. ByteTrack still receives every detector observation; only downstream
publication waits for the configured number of recent observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean


@dataclass
class _TrackState:
    observations: int
    last_seen_at: float
    classes: list[str]
    confidences: list[float]
    mean_confidence: float | None = None
    class_stability: float = 1.0


class TrackConfirmationGate:
    def __init__(
        self,
        *,
        minimum_observations: int,
        maximum_gap_s: float,
        evidence_window: int = 8,
        minimum_class_stability: float = 0.8,
    ) -> None:
        self.minimum_observations = max(1, minimum_observations)
        self.maximum_gap_s = max(0.1, maximum_gap_s)
        self.evidence_window = max(self.minimum_observations, evidence_window)
        self.minimum_class_stability = min(max(minimum_class_stability, 0.5), 1.0)
        self._tracks: dict[str, _TrackState] = {}

    def observe(
        self,
        track_id: str,
        timestamp: float,
        *,
        class_name: str | None = None,
        confidence: float | None = None,
        minimum_mean_confidence: float = 0.0,
        minimum_observations: int | None = None,
    ) -> tuple[bool, int]:
        previous = self._tracks.get(track_id)
        if previous is None or timestamp - previous.last_seen_at > self.maximum_gap_s:
            state = _TrackState(1, timestamp, [], [])
        else:
            state = previous
            state.observations += 1
            state.last_seen_at = timestamp
        if class_name is not None:
            state.classes.append(class_name)
            state.classes = state.classes[-self.evidence_window :]
            state.class_stability = state.classes.count(class_name) / len(state.classes)
        if confidence is not None:
            state.confidences.append(min(max(float(confidence), 0.0), 1.0))
            state.confidences = state.confidences[-self.evidence_window :]
            state.mean_confidence = fmean(state.confidences)
        self._tracks[track_id] = state
        self._expire(timestamp)
        stable_class = (
            class_name is None or state.class_stability >= self.minimum_class_stability
        )
        strong_mean = confidence is None or (
            state.mean_confidence is not None
            and state.mean_confidence >= minimum_mean_confidence
        )
        required_observations = max(
            1,
            self.minimum_observations
            if minimum_observations is None
            else minimum_observations,
        )
        return (
            state.observations >= required_observations
            and stable_class
            and strong_mean,
            state.observations,
        )

    def evidence(self, track_id: str) -> dict[str, float | None]:
        state = self._tracks.get(track_id)
        return {
            "mean_confidence": state.mean_confidence if state else None,
            "class_stability": state.class_stability if state else 0.0,
        }

    def _expire(self, now: float) -> None:
        self._tracks = {
            track_id: state
            for track_id, state in self._tracks.items()
            if now - state.last_seen_at <= self.maximum_gap_s
        }
