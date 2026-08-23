"""Relay authenticated V2X MQTT envelopes to the local API.

Run this only against a broker that uses TLS/mTLS in a deployed environment.
"""

import json
import logging
import os
import ssl
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import paho.mqtt.client as mqtt
from .config import get_settings
from .mqtt import configure_mqtt_transport
from .observability import configure_logging
from .service_health import ServiceHealth
from .service_auth import ServiceTokenProvider
from .v2x import create_heartbeat


LOGGER = logging.getLogger(__name__)


def main():
    settings = get_settings()
    settings.validate()
    configure_logging("sentinel-v2x", settings.log_level)
    health = ServiceHealth("sentinel-v2x", settings.service_health_port)
    health.start()
    if not settings.enable_v2x or not settings.v2x_shared_secret:
        raise SystemExit(
            "Set ENABLE_V2X=true and V2X_SHARED_SECRET before starting the V2X bridge."
        )
    api_url = os.getenv("API_URL", "http://api:8080")
    parsed_api = urlparse(api_url)
    if parsed_api.scheme not in {"http", "https"} or not parsed_api.hostname:
        raise SystemExit("API_URL must be an HTTP(S) endpoint.")
    token_provider = ServiceTokenProvider(
        api_url,
        settings.service_client_id,
        settings.service_client_secret_file,
        ca_cert=settings.service_ca_cert,
        client_cert=settings.service_client_cert,
        client_key=settings.service_client_key,
    )
    api_ssl_context = None
    if parsed_api.scheme == "https":
        if not (
            settings.service_ca_cert
            and settings.service_client_cert
            and settings.service_client_key
        ):
            raise SystemExit(
                "HTTPS API_URL requires service CA, certificate, and key paths."
            )
        api_ssl_context = ssl.create_default_context(cafile=settings.service_ca_cert)
        api_ssl_context.load_cert_chain(
            settings.service_client_cert, settings.service_client_key
        )
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{settings.v2x_source_id}-relay",
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
            mqtt_client.subscribe(settings.v2x_heartbeats_topic, qos=1)
            health.set_ready(True, transport="mqtt", subscriptions="active")
        else:
            health.set_ready(
                False, reason="mqtt_connection_rejected", reason_code=str(reason_code)
            )

    def on_disconnect(
        mqtt_client, userdata, disconnect_flags, reason_code, properties=None
    ):
        health.set_ready(
            False, reason="mqtt_disconnected", reason_code=str(reason_code)
        )

    def on_message(mqtt_client, userdata, message):
        try:
            data = json.loads(message.payload.decode("utf-8"))
            if message.topic == settings.v2x_events_topic:
                if data.get("source_id") == settings.v2x_source_id:
                    return
                endpoint = "/api/v2x/events"
            elif message.topic == settings.v2x_heartbeats_topic:
                endpoint = "/api/v2x/heartbeats"
            else:
                return
            headers = {
                "Content-Type": "application/json",
                "X-Correlation-ID": str(data.get("message_id", "v2x"))[:128],
                **token_provider.authorization_header(),
            }
            request = Request(
                f"{api_url}{endpoint}",
                data=json.dumps(data).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            # API_URL was restricted to HTTP(S) above.
            with urlopen(request, timeout=3, context=api_ssl_context) as response:  # nosec B310
                response.read()
        except Exception:
            LOGGER.warning(
                "V2X relay rejected message",
                extra={"event": "message_rejected", "component": "v2x"},
            )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(settings.mqtt_host, settings.mqtt_port, 30)
    client.loop_start()
    sequence = 0
    try:
        while True:
            sequence += 1
            heartbeat = create_heartbeat(
                settings.v2x_source_id,
                "gateway",
                settings.v2x_shared_secret,
                sequence,
                capabilities=["signed-event-relay", "peer-heartbeat", "replay-monitor"],
                transport="mqtt",
                firmware_version="sentinel-v2x/1",
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
        health.stop()


if __name__ == "__main__":
    main()
