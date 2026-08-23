"""Deterministic mission validation and statistics.

This module plans and validates only. It has no vehicle command transport and
cannot arm, upload, or activate a mission.
"""

from __future__ import annotations

import math

from .geofence import contains
from .schemas import (
    Geofence,
    Location,
    MissionDraft,
    MissionStatistics,
    MissionValidationIssue,
    MissionValidationResult,
)

EARTH_RADIUS_M = 6_371_008.8


def _orientation(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    return (second[1] - first[1]) * (third[0] - second[0]) - (
        second[0] - first[0]
    ) * (third[1] - second[1])


def _on_segment(
    first: tuple[float, float],
    point: tuple[float, float],
    second: tuple[float, float],
    *,
    epsilon: float = 1e-12,
) -> bool:
    return (
        min(first[0], second[0]) - epsilon
        <= point[0]
        <= max(first[0], second[0]) + epsilon
        and min(first[1], second[1]) - epsilon
        <= point[1]
        <= max(first[1], second[1]) + epsilon
    )


def segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    """Return whether two short local WGS84 segments touch or cross.

    Mission validation uses this planar test only for short operational routes.
    It deliberately treats touching a restricted boundary as a conflict.
    """
    first_orientation = _orientation(first_start, first_end, second_start)
    second_orientation = _orientation(first_start, first_end, second_end)
    third_orientation = _orientation(second_start, second_end, first_start)
    fourth_orientation = _orientation(second_start, second_end, first_end)
    if (first_orientation > 0) != (second_orientation > 0) and (
        third_orientation > 0
    ) != (fourth_orientation > 0):
        return True
    epsilon = 1e-12
    return any(
        (
            abs(orientation) <= epsilon
            and _on_segment(segment_start, point, segment_end)
        )
        for orientation, segment_start, point, segment_end in (
            (first_orientation, first_start, second_start, first_end),
            (second_orientation, first_start, second_end, first_end),
            (third_orientation, second_start, first_start, second_end),
            (fourth_orientation, second_start, first_end, second_end),
        )
    )


def segment_intersects_geofence(
    start: tuple[float, float],
    end: tuple[float, float],
    geofence: Geofence,
) -> bool:
    polygon = geofence.coordinates
    return any(
        segments_intersect(start, end, edge_start, edge_end)
        for edge_start, edge_end in zip(polygon, polygon[1:] + polygon[:1])
    )


def haversine_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Return great-circle distance without claiming terrain-following length."""
    lat_a, lon_a = map(math.radians, first)
    lat_b, lon_b = map(math.radians, second)
    delta_lat = lat_b - lat_a
    delta_lon = lon_b - lon_a
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def validate_mission(
    mission: MissionDraft, geofences: list[Geofence]
) -> MissionValidationResult:
    """Validate structure and deterministic restricted-zone conflicts."""
    issues: list[MissionValidationIssue] = []
    ordered = sorted(mission.waypoints, key=lambda item: item.sequence)
    sequences = [item.sequence for item in ordered]
    expected = list(range(len(ordered)))
    if sequences != expected:
        issues.append(
            MissionValidationIssue(
                severity="error",
                code="WAYPOINT_SEQUENCE",
                path="waypoints",
                message="Waypoint sequence numbers must be unique and contiguous from zero.",
            )
        )
    if not ordered:
        issues.append(
            MissionValidationIssue(
                severity="error",
                code="MISSION_EMPTY",
                path="waypoints",
                message="At least one waypoint is required before validation.",
            )
        )
    if any(item.command == "TAKEOFF" for item in ordered[1:]):
        issues.append(
            MissionValidationIssue(
                severity="error",
                code="TAKEOFF_ORDER",
                path="waypoints",
                message="TAKEOFF may appear only as the first mission item.",
            )
        )
    terminal_commands = {"LAND", "RETURN_TO_LAUNCH"}
    if any(item.command in terminal_commands for item in ordered[:-1]):
        issues.append(
            MissionValidationIssue(
                severity="error",
                code="TERMINAL_ORDER",
                path="waypoints",
                message="LAND or RETURN_TO_LAUNCH may appear only as the final item.",
            )
        )
    if ordered and ordered[-1].command not in terminal_commands:
        issues.append(
            MissionValidationIssue(
                severity="warning",
                code="NO_TERMINAL_ACTION",
                path=f"waypoints[{len(ordered) - 1}].command",
                message="Mission has no explicit LAND or RETURN_TO_LAUNCH terminal action.",
            )
        )

    restricted = [zone for zone in geofences if zone.restricted]
    for index, waypoint in enumerate(ordered):
        location = Location(
            latitude=waypoint.latitude,
            longitude=waypoint.longitude,
            approximate=False,
            method="reported",
        )
        for zone in restricted:
            if contains(location, zone):
                issues.append(
                    MissionValidationIssue(
                        severity="error",
                        code="RESTRICTED_ZONE_CONFLICT",
                        path=f"waypoints[{index}]",
                        message=f"Waypoint intersects restricted zone {zone.name!r}.",
                    )
                )

    for index, (start, end) in enumerate(zip(ordered, ordered[1:])):
        route_start = (start.latitude, start.longitude)
        route_end = (end.latitude, end.longitude)
        for zone in restricted:
            if segment_intersects_geofence(route_start, route_end, zone):
                issues.append(
                    MissionValidationIssue(
                        severity="error",
                        code="RESTRICTED_ROUTE_CROSSING",
                        path=f"waypoints[{index}:{index + 2}]",
                        message=(
                            "Mission leg touches or crosses restricted zone "
                            f"{zone.name!r}."
                        ),
                    )
                )

    positions = [(item.latitude, item.longitude) for item in ordered]
    total_distance = sum(
        haversine_m(first, second)
        for first, second in zip(positions, positions[1:])
    )
    max_range = None
    if mission.home is not None and positions:
        home = (mission.home.latitude, mission.home.longitude)
        max_range = max(haversine_m(home, position) for position in positions)
    speed = mission.cruise_speed_mps
    if speed is None:
        speeds = [item.speed_mps for item in ordered if item.speed_mps is not None]
        speed = sum(speeds) / len(speeds) if speeds else None
    holds = sum(item.hold_time_s or 0.0 for item in ordered)
    duration = total_distance / speed + holds if speed else None
    valid = not any(issue.severity == "error" for issue in issues)
    return MissionValidationResult(
        valid=valid,
        state="VALID" if valid else "INVALID",
        issues=issues,
        statistics=MissionStatistics(
            waypoint_count=len(ordered),
            total_distance_m=round(total_distance, 2),
            max_range_from_home_m=round(max_range, 2) if max_range is not None else None,
            estimated_duration_s=round(duration, 1) if duration is not None else None,
        ),
    )


ALLOWED_EVENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW": frozenset({"ACKNOWLEDGED", "UNDER_REVIEW", "DISMISSED"}),
    "ACKNOWLEDGED": frozenset({"UNDER_REVIEW", "RESOLVED", "DISMISSED"}),
    "UNDER_REVIEW": frozenset({"RESOLVED", "DISMISSED"}),
    "RESOLVED": frozenset(),
    "DISMISSED": frozenset(),
}


def event_transition_allowed(current: str, requested: str) -> bool:
    return requested in ALLOWED_EVENT_TRANSITIONS.get(current, frozenset())
