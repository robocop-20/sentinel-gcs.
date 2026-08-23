import time
from uuid import uuid4
from .schemas import Event, Geofence, Location


class EventEngine:
    def __init__(self, state_ttl_s: float = 900.0) -> None:
        self.state_ttl_s = max(state_ttl_s, 1.0)
        self._states: dict[tuple[str, str], tuple[bool, float]] = {}

    def observe(
        self,
        track_id: str,
        location: Location,
        geofence: Geofence,
        is_inside: bool,
        timestamp: float | None = None,
    ) -> Event | None:
        observed_at = time.time() if timestamp is None else timestamp
        cutoff = observed_at - self.state_ttl_s
        self._states = {
            state_key: state
            for state_key, state in self._states.items()
            if state[1] >= cutoff
        }
        key = (track_id, geofence.id)
        was_inside = self._states.get(key, (False, observed_at))[0]
        self._states[key] = (is_inside, observed_at)
        if is_inside == was_inside:
            return None
        entered = is_inside
        return Event(
            id=str(uuid4()),
            timestamp=observed_at,
            track_id=track_id,
            geofence_id=geofence.id,
            event_type="geofence_entry" if entered else "geofence_exit",
            severity="critical" if entered else "info",
            rule_id="geofence-transition",
            rule_version="1",
            location=location,
            message=f"{track_id} {'entered' if entered else 'exited'} {geofence.name}",
        )
