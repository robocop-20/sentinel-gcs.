"""Reference event-only V2X peer agent for drones, cameras and vehicles.

The adapter advertises signed liveness and receives verified security events.
It intentionally has no actuator, flight-control, vehicle-control or alert-rule
interface. A platform-specific integration can pass accepted events to an
authorised operator display without turning messages into automatic actions.
"""

from __future__ import annotations

import json
import os
import time

import paho.mqtt.client as mqtt

from .config import get_settings
from .mqtt import configure_mqtt_transport
from .schemas import V2XEnvelope
from .v2x import create_heartbeat, v2x_validation_reason


def main() -> None:
    settings = get_settings()
    device_id = os.getenv("V2X_DEVICE_ID", "").strip()
    device_type = os.getenv("V2X_DEVICE_TYPE", "").strip().lower()
    capabilities = [
        item.strip()
        for item in os.getenv("V2X_DEVICE_CAPABILITIES", "event-receiver").split(",")
        if item.strip()
    ]
    firmware = os.getenv("V2X_DEVICE_FIRMWARE", "unknown").strip() or None
    if not settings.enable_v2x or not settings.v2x_shared_secret:
        raise SystemExit("Set ENABLE_V2X=true and provision a V2X shared secret.")
    if not device_id or device_type not in {
        "drone",
        "camera",
        "vehicle",
        "infrastructure",
        "gateway",
    }:
        raise SystemExit("Set V2X_DEVICE_ID and a valid V2X_DEVICE_TYPE.")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=device_id,
        protocol=mqtt.MQTTv311,
        clean_session=False,
    )
    configure_mqtt_transport(client, settings)
    client.reconnect_delay_set(
        min_delay=max(settings.mqtt_reconnect_min_s, 1),
        max_delay=max(settings.mqtt_reconnect_max_s, settings.mqtt_reconnect_min_s),
    )

    def on_connect(mqtt_client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            mqtt_client.subscribe(settings.v2x_events_topic, qos=2)

    def on_message(mqtt_client, userdata, message):
        try:
            envelope = V2XEnvelope(**json.loads(message.payload.decode("utf-8")))
            reason = v2x_validation_reason(
                envelope, settings.v2x_shared_secret, settings.v2x_max_age_s
            )
            if reason != "accepted":
                print(f"Rejected V2X event: {reason}", flush=True)
                return
            event = envelope.event
            print(
                f"Verified advisory event {event.id}: {event.severity} {event.event_type} "
                f"from {envelope.source_id}",
                flush=True,
            )
        except Exception as exc:
            print(f"Rejected malformed V2X event: {type(exc).__name__}", flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(settings.mqtt_host, settings.mqtt_port, 30)
    client.loop_start()
    sequence = 0
    try:
        while True:
            sequence += 1
            heartbeat = create_heartbeat(
                device_id,
                device_type,
                settings.v2x_shared_secret,
                sequence,
                capabilities=capabilities,
                transport="mqtt",
                firmware_version=firmware,
            )
            client.publish(
                settings.v2x_heartbeats_topic,
                json.dumps(heartbeat),
                qos=1,
                retain=False,
            )
            time.sleep(max(settings.v2x_heartbeat_interval_s, 1.0))
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
