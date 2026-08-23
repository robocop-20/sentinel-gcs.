"""Deterministic anonymous track-behaviour analytics.

This module consumes only persistent Track IDs, object class, time, and
geolocated observations. It uses no face features, identity, or LLM decision.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from uuid import uuid4

from .schemas import Event, Location


@dataclass(frozen=True)
class Observation:
    timestamp: float
    object_class: str
    location: Location


def distance_meters(first: Location, second: Location) -> float:
    """Haversine surface distance; adequate for rule thresholds at this scale."""
    earth_radius_m = 6_371_000.0
    delta_lat = radians(second.latitude - first.latitude)
    delta_lon = radians(second.longitude - first.longitude)
    lat_a, lat_b = radians(first.latitude), radians(second.latitude)
    haversine = (
        sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_m * asin(sqrt(haversine))


class BehaviorEngine:
    """Stateful rule engine with explicit thresholds and event cooldowns."""

    def __init__(
        self,
        *,
        loiter_window_s: float,
        loiter_radius_m: float,
        proximity_distance_m: float,
        event_cooldown_s: float,
        track_ttl_s: float,
    ) -> None:
        self.loiter_window_s = loiter_window_s
        self.loiter_radius_m = loiter_radius_m
        self.proximity_distance_m = proximity_distance_m
        self.event_cooldown_s = event_cooldown_s
        self.track_ttl_s = track_ttl_s
        self.history: dict[str, deque[Observation]] = defaultdict(deque)
        self.latest: dict[str, Observation] = {}
        self._last_emitted: dict[tuple[str, str], float] = {}

    def _is_cooled_down(self, key: tuple[str, str], timestamp: float) -> bool:
        previous = self._last_emitted.get(key)
        if previous is not None and timestamp - previous < self.event_cooldown_s:
            return False
        self._last_emitted[key] = timestamp
        return True

    def _expire(self, timestamp: float) -> None:
        cutoff = timestamp - self.track_ttl_s
        for track_id, observations in list(self.history.items()):
            while observations and observations[0].timestamp < cutoff:
                observations.popleft()
            if not observations:
                self.history.pop(track_id, None)
                self.latest.pop(track_id, None)

    def observe(
        self,
        track_id: str,
        object_class: str,
        location: Location,
        timestamp: float | None = None,
    ) -> list[Event]:
        observed_at = time.time() if timestamp is None else timestamp
        self._expire(observed_at)
        observation = Observation(observed_at, object_class, location)
        observations = self.history[track_id]
        observations.append(observation)
        self.latest[track_id] = observation
        events: list[Event] = []

        window_start = observed_at - self.loiter_window_s
        window = [entry for entry in observations if entry.timestamp >= window_start]
        if observations and observations[0].timestamp <= window_start:
            anchor = window[-1].location
            if all(
                distance_meters(anchor, entry.location) <= self.loiter_radius_m
                for entry in window
            ):
                key = (track_id, "loitering")
                if self._is_cooled_down(key, observed_at):
                    events.append(
                        Event(
                            id=str(uuid4()),
                            timestamp=observed_at,
                            event_type="loitering",
                            severity="warning",
                            rule_id="anonymous-loiter",
                            rule_version="1",
                            track_id=track_id,
                            geofence_id="behavior:loitering",
                            location=location,
                            message=(
                                f"{track_id} remained within {self.loiter_radius_m:g} m for at least "
                                f"{self.loiter_window_s:g} s"
                            ),
                        )
                    )

        for other_track_id, other in self.latest.items():
            if other_track_id == track_id or abs(observed_at - other.timestamp) > 2:
                continue
            classes = {object_class, other.object_class}
            if "person" not in classes or not classes.intersection(
                {"vehicle", "vessel"}
            ):
                continue
            separation = distance_meters(location, other.location)
            pair_id = "|".join(sorted((track_id, other_track_id)))
            if separation <= self.proximity_distance_m and self._is_cooled_down(
                (pair_id, "proximity"), observed_at
            ):
                events.append(
                    Event(
                        id=str(uuid4()),
                        timestamp=observed_at,
                        event_type="proximity_warning",
                        severity="warning",
                        rule_id="person-mobile-asset-proximity",
                        rule_version="1",
                        track_id=track_id,
                        geofence_id="behavior:proximity",
                        location=location,
                        message=(
                            f"{track_id} is {separation:.1f} m from {other_track_id}; "
                            "person/vehicle-vessel proximity threshold reached"
                        ),
                    )
                )
        return events
