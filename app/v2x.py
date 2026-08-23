import hashlib
import hmac
import json
import time
from uuid import uuid4
from .schemas import Event, Telemetry, V2XEnvelope, V2XHeartbeat, V2XObservation


def _canonical_payload(envelope: dict) -> bytes:
    unsigned = {key: value for key, value in envelope.items() if key != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_observation(
    event: Event, track: dict | None, telemetry: Telemetry | None
) -> V2XObservation:
    """Attach field context without coupling the V2X layer to the detector."""
    geofence_status = {
        "geofence_entry": "entered",
        "geofence_exit": "exited",
    }.get(event.event_type, "unknown")
    return V2XObservation(
        object_type=track.get("class") if track else None,
        model_class=track.get("model_class") if track else None,
        track_id=event.track_id,
        detection_confidence=track.get("confidence") if track else None,
        observed_at=track.get("timestamp") if track else event.timestamp,
        source_camera_id=track.get("source") if track else None,
        heading_deg=telemetry.heading_deg if telemetry else None,
        velocity_mps=telemetry.ground_speed_mps if telemetry else None,
        altitude_m=telemetry.altitude_m if telemetry else None,
        geofence_status=geofence_status,
        bbox=track.get("bbox") if track else None,
    )


def create_envelope(
    event: Event,
    source_id: str,
    secret: str,
    track: dict | None = None,
    telemetry: Telemetry | None = None,
) -> dict:
    envelope = {
        "protocol": "sentinel-v2x/1",
        "message_id": str(uuid4()),
        "source_id": source_id,
        "sent_at": float(time.time()),
        "event": event.model_dump(mode="json"),
        "observation": create_observation(event, track, telemetry).model_dump(
            mode="json"
        ),
    }
    envelope["signature"] = hmac.new(
        secret.encode(), _canonical_payload(envelope), hashlib.sha256
    ).hexdigest()
    return envelope


def create_heartbeat(
    device_id: str,
    device_type: str,
    secret: str,
    sequence: int,
    *,
    capabilities: list[str] | None = None,
    transport: str = "mqtt",
    reported_status: str = "online",
    firmware_version: str | None = None,
    sent_at: float | None = None,
) -> dict:
    """Create a signed peer-presence message with no command authority."""
    heartbeat = {
        "protocol": "sentinel-v2x-heartbeat/1",
        "message_id": str(uuid4()),
        "device_id": device_id,
        "device_type": device_type,
        # Normalise before signing so validation after Pydantic parsing uses
        # byte-identical canonical JSON (an input integer becomes a float).
        "sent_at": float(time.time() if sent_at is None else sent_at),
        "sequence": sequence,
        "reported_status": reported_status,
        "transport": transport,
        "capabilities": capabilities or [],
        "firmware_version": firmware_version,
    }
    heartbeat["signature"] = hmac.new(
        secret.encode(), _canonical_payload(heartbeat), hashlib.sha256
    ).hexdigest()
    # Validate the adapter contract before anything is published.
    return V2XHeartbeat(**heartbeat).model_dump(mode="json")


def verify_envelope(envelope: V2XEnvelope, secret: str, max_age_s: int) -> bool:
    return v2x_validation_reason(envelope, secret, max_age_s) == "accepted"


def v2x_validation_reason(envelope: V2XEnvelope, secret: str, max_age_s: int) -> str:
    """Return a non-sensitive reason suitable for defensive audit logging."""
    if not secret:
        return "missing_secret"
    if abs(time.time() - envelope.sent_at) > max_age_s:
        return "expired"
    data = envelope.model_dump(mode="json")
    expected = hmac.new(
        secret.encode(), _canonical_payload(data), hashlib.sha256
    ).hexdigest()
    return (
        "accepted"
        if hmac.compare_digest(envelope.signature, expected)
        else "invalid_signature"
    )


def v2x_heartbeat_validation_reason(
    heartbeat: V2XHeartbeat, secret: str, max_age_s: int
) -> str:
    if not secret:
        return "missing_secret"
    if abs(time.time() - heartbeat.sent_at) > max_age_s:
        return "expired"
    data = heartbeat.model_dump(mode="json")
    expected = hmac.new(
        secret.encode(), _canonical_payload(data), hashlib.sha256
    ).hexdigest()
    return (
        "accepted"
        if hmac.compare_digest(heartbeat.signature, expected)
        else "invalid_signature"
    )
