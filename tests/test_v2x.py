from unittest.mock import patch

from app.schemas import Event, Location, Telemetry, V2XEnvelope, V2XHeartbeat
from app.v2x import (
    create_envelope,
    create_heartbeat,
    verify_envelope,
    v2x_heartbeat_validation_reason,
)


def test_signed_v2x_event_verifies():
    event = Event(
        id="00000000-0000-0000-0000-000000000001",
        timestamp=1_700_000_000,
        event_type="geofence_entry",
        severity="critical",
        track_id="T-1",
        geofence_id="zone-a",
        message="entry",
        location=Location(latitude=17.686, longitude=83.218),
    )
    with patch("app.v2x.time.time", return_value=1_700_000_000):
        envelope = V2XEnvelope(
            **create_envelope(event, "ground-1", "shared-test-secret")
        )
        assert verify_envelope(envelope, "shared-test-secret", 30)


def test_envelope_carries_observation_context_without_changing_event():
    event = Event(
        id="00000000-0000-0000-0000-000000000002",
        timestamp=1_700_000_000,
        event_type="geofence_entry",
        severity="critical",
        track_id="T-2",
        geofence_id="zone-a",
        message="entry",
        location=Location(latitude=17.686, longitude=83.218),
        risk_score=90,
    )
    telemetry = Telemetry(
        timestamp=1_700_000_000,
        latitude=17.686,
        longitude=83.218,
        altitude_m=20,
        heading_deg=90,
        ground_speed_mps=8,
    )
    track = {
        "class": "vehicle",
        "model_class": "truck",
        "confidence": 0.91,
        "timestamp": event.timestamp,
        "source": "camera-01",
        "bbox": {"x": 10, "y": 20, "width": 30, "height": 40},
    }
    envelope = V2XEnvelope(
        **create_envelope(event, "ground-1", "shared-test-secret", track, telemetry)
    )
    assert envelope.observation.object_type == "vehicle"
    assert envelope.observation.heading_deg == 90
    assert envelope.event.severity == "critical"


def test_signed_v2x_heartbeat_verifies_and_tampering_fails():
    heartbeat = V2XHeartbeat(
        **create_heartbeat(
            "patrol-vehicle-07",
            "vehicle",
            "shared-test-secret",
            42,
            capabilities=["event-receiver", "gps"],
            sent_at=1_700_000_000,
        )
    )
    with patch("app.v2x.time.time", return_value=1_700_000_000):
        assert (
            v2x_heartbeat_validation_reason(heartbeat, "shared-test-secret", 30)
            == "accepted"
        )
        tampered = heartbeat.model_copy(update={"sequence": 43})
        assert (
            v2x_heartbeat_validation_reason(tampered, "shared-test-secret", 30)
            == "invalid_signature"
        )
