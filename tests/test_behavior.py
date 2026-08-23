from app.behavior import BehaviorEngine
from app.schemas import Location


def engine() -> BehaviorEngine:
    return BehaviorEngine(
        loiter_window_s=60,
        loiter_radius_m=8,
        proximity_distance_m=8,
        event_cooldown_s=300,
        track_ttl_s=600,
    )


def test_stationary_anonymous_track_emits_one_loitering_event():
    behavior = engine()
    location = Location(latitude=17.686, longitude=83.218)
    assert behavior.observe("camera-01-T-007", "person", location, 0) == []
    assert behavior.observe("camera-01-T-007", "person", location, 30) == []
    events = behavior.observe("camera-01-T-007", "person", location, 61)
    assert [event.event_type for event in events] == ["loitering"]
    assert behavior.observe("camera-01-T-007", "person", location, 62) == []


def test_person_vehicle_proximity_emits_warning_without_identity():
    behavior = engine()
    person_location = Location(latitude=17.686, longitude=83.218)
    nearby_vehicle = Location(latitude=17.68602, longitude=83.218)
    assert behavior.observe("camera-01-T-007", "person", person_location, 10) == []
    events = behavior.observe("camera-01-T-008", "vehicle", nearby_vehicle, 10.5)
    assert [event.event_type for event in events] == ["proximity_warning"]
    assert events[0].track_id == "camera-01-T-008"
