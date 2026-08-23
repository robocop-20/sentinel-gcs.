from pathlib import Path

from app.durable_queue import DurableQueue


def queue_at(path: Path) -> DurableQueue:
    return DurableQueue(str(path), max_records=100, max_bytes=2 * 1024 * 1024)


def test_outbox_survives_process_reopen(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    first = queue_at(path)
    record_id = first.enqueue(
        "mqtt", "ground/events", {"id": "event-1"}, qos=2, priority=100
    )

    reopened = queue_at(path)
    record = reopened.next_due("mqtt")
    assert record is not None
    assert record.id == record_id
    assert record.qos == 2
    assert record.payload == {"id": "event-1"}
    reopened.acknowledge(record.id)
    assert reopened.next_due("mqtt") is None


def test_low_value_state_is_coalesced_but_events_are_not(tmp_path: Path) -> None:
    queue = queue_at(tmp_path / "outbox.sqlite3")
    queue.enqueue(
        "mqtt",
        "ground/tracks",
        {"track_id": "T-1", "confidence": 0.5},
        coalesce_key="track:T-1",
    )
    queue.enqueue(
        "mqtt",
        "ground/tracks",
        {"track_id": "T-1", "confidence": 0.8},
        coalesce_key="track:T-1",
    )
    assert queue.stats()["mqtt"]["pending"] == 1
    record = queue.next_due("mqtt")
    assert record is not None
    assert record.payload["confidence"] == 0.8


def test_critical_failure_is_atomically_dead_lettered(tmp_path: Path) -> None:
    queue = queue_at(tmp_path / "outbox.sqlite3")
    queue.enqueue("mqtt", "ground/events", {"id": "E-7"}, qos=2, priority=100)
    record = queue.next_due("mqtt")
    assert record is not None
    queue.dead_letter(
        record,
        dead_letter_topic="sentinel/dead-letter/events",
        error="TimeoutError",
    )
    dead_letter = queue.next_due("mqtt")
    assert dead_letter is not None
    assert dead_letter.destination == "sentinel/dead-letter/events"
    assert dead_letter.payload["original_payload"]["id"] == "E-7"
    assert queue.stats()["mqtt"]["dead_letters"] == 1


def test_idempotency_claim_is_atomic_and_releasable(tmp_path: Path) -> None:
    queue = queue_at(tmp_path / "outbox.sqlite3")
    assert queue.claim_idempotency("detection:batch-1", 60) is True
    assert queue.claim_idempotency("detection:batch-1", 60) is False
    queue.release_idempotency("detection:batch-1")
    assert queue.claim_idempotency("detection:batch-1", 60) is True
