import time

from app.config import Settings
from app.schemas import Event, Location, Telemetry, V2XEnvelope
from app.security_monitor import SecurityMonitor
from app.v2x import create_envelope


def telemetry(timestamp: float, latitude: float, heading_deg: float = 0) -> Telemetry:
    return Telemetry(
        timestamp=timestamp,
        latitude=latitude,
        longitude=83.218,
        altitude_m=20,
        heading_deg=heading_deg,
        source="mavlink-test",
    )


def test_telemetry_jump_is_flagged_without_rejecting_the_sample():
    monitor = SecurityMonitor(
        Settings(security_max_ground_speed_mps=50, security_finding_cooldown_s=1)
    )
    assert monitor.observe_telemetry(telemetry(100, 17.686), received_at=100) == []
    findings = monitor.observe_telemetry(telemetry(101, 17.706), received_at=101)
    assert {finding.code for finding in findings} == {"gps_kinematic_jump"}
    assert findings[0].advisory_only is True


def test_telemetry_timestamp_regression_is_flagged():
    monitor = SecurityMonitor(Settings(security_finding_cooldown_s=1))
    monitor.observe_telemetry(telemetry(100, 17.686), received_at=100)
    findings = monitor.observe_telemetry(telemetry(99, 17.686), received_at=100)
    assert any(
        finding.code == "telemetry_replay_or_clock_regression" for finding in findings
    )


def test_stale_telemetry_is_rate_limited():
    monitor = SecurityMonitor(
        Settings(security_telemetry_stale_s=5, security_finding_cooldown_s=20)
    )
    sample = telemetry(100, 17.686)
    monitor.observe_telemetry(sample, received_at=100)
    assert [
        finding.code for finding in monitor.check_telemetry_freshness(sample, now=106)
    ] == ["telemetry_stale"]
    assert monitor.check_telemetry_freshness(sample, now=110) == []


def test_duplicate_signed_v2x_message_is_reported():
    monitor = SecurityMonitor(Settings(v2x_max_age_s=30, security_finding_cooldown_s=1))
    event = Event(
        id="00000000-0000-0000-0000-000000000003",
        timestamp=time.time(),
        track_id="track-1",
        geofence_id="zone-a",
        event_type="geofence_entry",
        severity="warning",
        message="entry",
        location=Location(latitude=17.686, longitude=83.218),
    )
    envelope = V2XEnvelope(**create_envelope(event, "peer-1", "shared-secret"))
    assert monitor.observe_v2x(envelope) is None
    finding = monitor.observe_v2x(envelope)
    assert finding is not None
    assert finding.code == "v2x_replay_detected"
