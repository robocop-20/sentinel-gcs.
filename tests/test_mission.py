import pytest
from pydantic import ValidationError

from app.geofence import DEFAULT_GEOFENCE
from app.mission import event_transition_allowed, validate_mission
from app.schemas import Location, MissionDraft, MissionWaypoint


def waypoint(sequence: int, latitude: float, longitude: float, command="WAYPOINT"):
    return MissionWaypoint(
        sequence=sequence,
        command=command,
        latitude=latitude,
        longitude=longitude,
        altitude_m=60,
    )


def test_valid_mission_computes_distance_and_duration():
    mission = MissionDraft(
        name="Bench route",
        vehicle_id="vehicle-01",
        home=Location(
            latitude=0,
            longitude=0,
            approximate=False,
            method="reported",
        ),
        cruise_speed_mps=10,
        waypoints=[
            waypoint(0, 0, 0, "TAKEOFF"),
            waypoint(1, 0, 0.001),
            waypoint(2, 0, 0.002, "RETURN_TO_LAUNCH"),
        ],
    )

    result = validate_mission(mission, [])

    assert result.valid is True
    assert 220 < result.statistics.total_distance_m < 225
    assert 22 < result.statistics.estimated_duration_s < 23


def test_mission_rejects_non_contiguous_sequence():
    mission = MissionDraft(
        name="Broken sequence",
        vehicle_id="vehicle-01",
        waypoints=[waypoint(0, 0, 0), waypoint(2, 0, 0.001)],
    )

    result = validate_mission(mission, [])

    assert result.valid is False
    assert "WAYPOINT_SEQUENCE" in {issue.code for issue in result.issues}


def test_mission_rejects_restricted_zone_intersection():
    latitude, longitude = DEFAULT_GEOFENCE.coordinates[0]
    mission = MissionDraft(
        name="Restricted route",
        vehicle_id="vehicle-01",
        waypoints=[
            waypoint(0, latitude + 0.0001, longitude + 0.0001),
            waypoint(1, 0, 0, "RETURN_TO_LAUNCH"),
        ],
    )

    result = validate_mission(mission, [DEFAULT_GEOFENCE])

    assert result.valid is False
    assert "RESTRICTED_ZONE_CONFLICT" in {issue.code for issue in result.issues}


def test_mission_rejects_leg_crossing_restricted_zone_with_clear_endpoints():
    latitudes = [point[0] for point in DEFAULT_GEOFENCE.coordinates]
    longitudes = [point[1] for point in DEFAULT_GEOFENCE.coordinates]
    latitude = (min(latitudes) + max(latitudes)) / 2
    mission = MissionDraft(
        name="Crossing route",
        vehicle_id="vehicle-01",
        waypoints=[
            waypoint(0, latitude, min(longitudes) - 0.001),
            waypoint(
                1,
                latitude,
                max(longitudes) + 0.001,
                "RETURN_TO_LAUNCH",
            ),
        ],
    )

    result = validate_mission(mission, [DEFAULT_GEOFENCE])

    assert result.valid is False
    assert "RESTRICTED_ROUTE_CROSSING" in {
        issue.code for issue in result.issues
    }


def test_mission_id_must_be_a_uuid():
    with pytest.raises(ValidationError):
        MissionDraft(id="not-a-database-uuid", name="Invalid", vehicle_id="v-1")


def test_event_lifecycle_is_forward_only_and_terminal():
    assert event_transition_allowed("NEW", "ACKNOWLEDGED") is True
    assert event_transition_allowed("ACKNOWLEDGED", "UNDER_REVIEW") is True
    assert event_transition_allowed("UNDER_REVIEW", "RESOLVED") is True
    assert event_transition_allowed("RESOLVED", "UNDER_REVIEW") is False
    assert event_transition_allowed("DISMISSED", "ACKNOWLEDGED") is False
