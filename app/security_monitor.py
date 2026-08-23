"""Deterministic defensive monitoring for telemetry and signed V2X traffic.

This layer detects integrity symptoms. It neither pilots a drone nor blocks a
network peer; operators and fixed response playbooks retain that authority.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from uuid import uuid4

from .config import Settings
from .schemas import SecurityFinding, Telemetry, V2XEnvelope


EARTH_RADIUS_M = 6_371_000.0


def _ground_distance_m(first: Telemetry, second: Telemetry) -> float:
    lat_1, lon_1 = math.radians(first.latitude), math.radians(first.longitude)
    lat_2, lon_2 = math.radians(second.latitude), math.radians(second.longitude)
    half_latitude, half_longitude = (lat_2 - lat_1) / 2, (lon_2 - lon_1) / 2
    haversine = (
        math.sin(half_latitude) ** 2
        + math.cos(lat_1) * math.cos(lat_2) * math.sin(half_longitude) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))


@dataclass(frozen=True)
class _FindingSpec:
    category: str
    code: str
    severity: str
    message: str
    evidence: dict[str, float | str]
    recommended_action: str


class SecurityMonitor:
    """Stateful, rate-limited integrity checks with transparent thresholds."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._previous_telemetry: dict[str, Telemetry] = {}
        self._seen_v2x_messages: dict[str, float] = {}
        self._last_emitted: dict[tuple[str, str], float] = {}

    def _finding(
        self, source_id: str, spec: _FindingSpec, now: float
    ) -> SecurityFinding | None:
        key = (source_id, spec.code)
        cooldown = max(self.settings.security_finding_cooldown_s, 1.0)
        if now - self._last_emitted.get(key, float("-inf")) < cooldown:
            return None
        self._last_emitted[key] = now
        return SecurityFinding(
            id=str(uuid4()),
            timestamp=now,
            source_id=source_id,
            category=spec.category,
            code=spec.code,
            severity=spec.severity,
            message=spec.message,
            evidence=spec.evidence,
            recommended_action=spec.recommended_action,
        )

    def observe_telemetry(
        self, telemetry: Telemetry, *, received_at: float | None = None
    ) -> list[SecurityFinding]:
        """Check one telemetry observation without rejecting it."""
        now = time.time() if received_at is None else received_at
        previous = self._previous_telemetry.get(telemetry.source)
        candidates: list[_FindingSpec] = []
        if telemetry.timestamp > now + self.settings.security_max_clock_skew_s:
            candidates.append(
                _FindingSpec(
                    "telemetry_integrity",
                    "telemetry_future_timestamp",
                    "warning",
                    "Telemetry timestamp is ahead of the ground-station clock.",
                    {"offset_s": round(telemetry.timestamp - now, 3)},
                    "Verify time synchronisation before using this pose for geolocation.",
                )
            )
        if previous is not None:
            elapsed_s = telemetry.timestamp - previous.timestamp
            if elapsed_s <= 0:
                candidates.append(
                    _FindingSpec(
                        "telemetry_integrity",
                        "telemetry_replay_or_clock_regression",
                        "critical",
                        "Telemetry time did not advance for this source.",
                        {"elapsed_s": round(elapsed_s, 3)},
                        "Reacquire authenticated telemetry and investigate replay or clock faults.",
                    )
                )
            else:
                distance_m = _ground_distance_m(previous, telemetry)
                implied_speed = distance_m / elapsed_s
                if implied_speed > self.settings.security_max_ground_speed_mps:
                    candidates.append(
                        _FindingSpec(
                            "telemetry_integrity",
                            "gps_kinematic_jump",
                            "critical",
                            "Successive GPS positions imply an implausible ground speed.",
                            {
                                "implied_speed_mps": round(implied_speed, 2),
                                "threshold_mps": self.settings.security_max_ground_speed_mps,
                                "interval_s": round(elapsed_s, 3),
                            },
                            "Treat position as untrusted; verify GNSS and flight-controller telemetry.",
                        )
                    )
                heading_delta = abs(
                    ((telemetry.heading_deg - previous.heading_deg + 180) % 360) - 180
                )
                heading_rate = heading_delta / elapsed_s
                if heading_rate > self.settings.security_max_heading_rate_deg_s:
                    candidates.append(
                        _FindingSpec(
                            "telemetry_integrity",
                            "imu_heading_discontinuity",
                            "warning",
                            "Heading changed faster than the configured integrity bound.",
                            {
                                "heading_rate_deg_s": round(heading_rate, 2),
                                "threshold_deg_s": self.settings.security_max_heading_rate_deg_s,
                            },
                            "Check IMU calibration and compare the next authenticated pose samples.",
                        )
                    )
        level = (
            max(abs(telemetry.roll_deg), abs(telemetry.pitch_deg))
            <= self.settings.security_level_attitude_deg
        )
        if telemetry.range_m is not None and level:
            difference = abs(telemetry.range_m - telemetry.altitude_m)
            if difference > self.settings.security_lidar_altitude_delta_m:
                candidates.append(
                    _FindingSpec(
                        "telemetry_integrity",
                        "lidar_altitude_disagreement",
                        "warning",
                        "Downward range and altitude disagree while the aircraft is near level.",
                        {
                            "difference_m": round(difference, 2),
                            "threshold_m": self.settings.security_lidar_altitude_delta_m,
                        },
                        "Validate the range sensor, altitude reference, and terrain assumptions.",
                    )
                )
        if (
            telemetry.link_quality_percent is not None
            and telemetry.link_quality_percent
            < self.settings.security_min_link_quality_percent
        ):
            candidates.append(
                _FindingSpec(
                    "telemetry_integrity",
                    "telemetry_link_degraded",
                    "warning",
                    "Telemetry link quality is below the configured defensive threshold.",
                    {
                        "link_quality_percent": telemetry.link_quality_percent,
                        "threshold_percent": self.settings.security_min_link_quality_percent,
                    },
                    "Check radio link quality and retain local failsafe procedures.",
                )
            )
        self._previous_telemetry[telemetry.source] = telemetry
        return [
            finding
            for spec in candidates
            if (finding := self._finding(telemetry.source, spec, now))
        ]

    def check_telemetry_freshness(
        self, telemetry: Telemetry | None, *, now: float | None = None
    ) -> list[SecurityFinding]:
        if telemetry is None:
            return []
        observed_at = time.time() if now is None else now
        age_s = observed_at - telemetry.timestamp
        if age_s <= self.settings.security_telemetry_stale_s:
            return []
        spec = _FindingSpec(
            "telemetry_integrity",
            "telemetry_stale",
            "warning",
            "No recent telemetry has arrived from this source.",
            {
                "age_s": round(age_s, 2),
                "threshold_s": self.settings.security_telemetry_stale_s,
            },
            "Reacquire the authenticated telemetry link before relying on geolocation.",
        )
        finding = self._finding(telemetry.source, spec, observed_at)
        return [finding] if finding else []

    def observe_v2x(
        self, envelope: V2XEnvelope, *, now: float | None = None
    ) -> SecurityFinding | None:
        """Return an advisory finding for a repeated, otherwise-valid V2X ID."""
        observed_at = time.time() if now is None else now
        expiry = observed_at - max(self.settings.v2x_max_age_s, 1)
        self._seen_v2x_messages = {
            message_id: seen_at
            for message_id, seen_at in self._seen_v2x_messages.items()
            if seen_at >= expiry
        }
        if envelope.message_id in self._seen_v2x_messages:
            spec = _FindingSpec(
                "v2x_authentication",
                "v2x_replay_detected",
                "critical",
                "A signed V2X message ID was received more than once.",
                {"message_age_s": round(observed_at - envelope.sent_at, 3)},
                "Reject the replay and investigate the peer or transport path.",
            )
            return self._finding(envelope.source_id, spec, observed_at)
        self._seen_v2x_messages[envelope.message_id] = observed_at
        return None

    def rejected_v2x(
        self, source_id: str, reason: str, *, now: float | None = None
    ) -> SecurityFinding | None:
        observed_at = time.time() if now is None else now
        specifications = {
            "expired": _FindingSpec(
                "v2x_authentication",
                "v2x_expired_message",
                "warning",
                "A V2X message was outside the allowed age window.",
                {},
                "Check peer clocks and reject stale traffic.",
            ),
            "invalid_signature": _FindingSpec(
                "v2x_authentication",
                "v2x_invalid_signature",
                "critical",
                "A V2X message failed signature verification.",
                {},
                "Reject the peer message and investigate credentials or transport integrity.",
            ),
            "replay": _FindingSpec(
                "v2x_authentication",
                "v2x_replay_detected",
                "critical",
                "A signed V2X sequence was repeated or moved backwards.",
                {},
                "Reject the replay and investigate the peer or transport path.",
            ),
        }
        spec = specifications.get(reason)
        return (
            self._finding(source_id or "unknown-v2x-peer", spec, observed_at)
            if spec
            else None
        )

    def health(self) -> dict:
        return {
            "enabled": self.settings.enable_security_monitor,
            "telemetry_sources": sorted(self._previous_telemetry),
            "v2x_replay_cache": len(self._seen_v2x_messages),
            "mqtt_tls_configured": self.settings.mqtt_tls_enabled,
            "automatic_actions": False,
        }
