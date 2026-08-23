import json
import logging
import ssl
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from .config import Settings

LOGGER = logging.getLogger(__name__)


def qos_for_topic(settings: Settings, topic: str) -> int:
    """Use exactly-once MQTT delivery for evidentiary/security event topics."""
    qos2_topics = {
        "ground/events",
        settings.v2x_events_topic,
        settings.security_findings_topic,
        settings.evidence_requests_topic,
        settings.mqtt_dead_letter_topic,
    }
    return 2 if topic in qos2_topics else 1


def configure_mqtt_transport(client: mqtt.Client, settings: Settings) -> None:
    """Apply authenticated transport without weakening certificate checks."""
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    if settings.mqtt_tls_enabled:
        if not settings.mqtt_ca_cert:
            raise ValueError("MQTT_TLS_ENABLED requires MQTT_CA_CERT")
        client.tls_set(
            ca_certs=settings.mqtt_ca_cert,
            certfile=settings.mqtt_client_cert or None,
            keyfile=settings.mqtt_client_key or None,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set(False)


class MqttPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id="sentinel-api",
            protocol=mqtt.MQTTv311,
            clean_session=False,
        )
        self.connected = False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        try:
            configure_mqtt_transport(self.client, settings)
            self.client.reconnect_delay_set(
                min_delay=max(settings.mqtt_reconnect_min_s, 1),
                max_delay=max(
                    settings.mqtt_reconnect_max_s, settings.mqtt_reconnect_min_s
                ),
            )
            self.client.max_inflight_messages_set(20)
            # The application outbox owns offline persistence. Do not create a
            # second unbounded in-memory queue inside Paho.
            self.client.max_queued_messages_set(1)
            self.client.connect_async(settings.mqtt_host, settings.mqtt_port, 30)
            self.client.loop_start()
        except Exception as exc:
            LOGGER.warning("MQTT unavailable: %s", exc)

    def _on_connect(
        self,
        client: Any,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any | None = None,
    ) -> None:
        self.connected = reason_code == 0

    def _on_disconnect(
        self,
        client: Any,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any | None = None,
    ) -> None:
        self.connected = False

    def publish(
        self, topic: str, data: dict[str, Any], qos: int | None = None
    ) -> None:
        if not self.connected:
            raise ConnectionError("MQTT is disconnected")
        delivery_qos = qos_for_topic(self.settings, topic) if qos is None else qos
        result = self.client.publish(topic, json.dumps(data), qos=delivery_qos)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT publish was rejected with status {result.rc}")
        try:
            result.wait_for_publish(timeout=self.settings.mqtt_publish_timeout_s)
        except RuntimeError as exc:
            raise ConnectionError("MQTT publish acknowledgement failed") from exc
        if not result.is_published():
            raise TimeoutError(
                f"MQTT QoS {delivery_qos} acknowledgement timed out for {topic}"
            )

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
