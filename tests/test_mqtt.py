from types import SimpleNamespace

from app.mqtt import MqttPublisher, qos_for_topic


def test_disconnect_clears_transport_health() -> None:
    publisher = MqttPublisher.__new__(MqttPublisher)
    publisher.connected = True
    publisher._on_disconnect(None, None, None, 0)
    assert publisher.connected is False


def test_publish_does_not_silently_drop_while_disconnected() -> None:
    publisher = MqttPublisher.__new__(MqttPublisher)
    publisher.connected = False
    try:
        publisher.publish("test/topic", {"ok": True})
    except ConnectionError:
        return
    raise AssertionError("disconnected MQTT publish was silently accepted")


def test_evidentiary_event_topics_use_qos_two() -> None:
    settings = SimpleNamespace(
        v2x_events_topic="sentinel/v2x/events",
        security_findings_topic="ground/security/findings",
        evidence_requests_topic="ground/evidence/requests",
        mqtt_dead_letter_topic="sentinel/dead-letter/events",
    )
    assert qos_for_topic(settings, "ground/events") == 2
    assert qos_for_topic(settings, "ground/tracks") == 1


def test_publish_waits_for_broker_acknowledgement() -> None:
    class PublishInfo:
        rc = 0

        def __init__(self) -> None:
            self.waited = False

        def wait_for_publish(self, timeout: float) -> None:
            assert timeout == 3
            self.waited = True

        def is_published(self) -> bool:
            return self.waited

    class Client:
        def __init__(self) -> None:
            self.info = PublishInfo()
            self.qos = None

        def publish(self, topic: str, payload: str, qos: int):
            self.qos = qos
            return self.info

    publisher = MqttPublisher.__new__(MqttPublisher)
    publisher.connected = True
    publisher.settings = SimpleNamespace(mqtt_publish_timeout_s=3)
    publisher.client = Client()
    publisher.publish("ground/events", {"id": "E-1"}, qos=2)
    assert publisher.client.qos == 2
    assert publisher.client.info.waited is True
