import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.durable_queue import DurableQueue
from app.events import EventEngine
from app.pipeline import LayeredPipeline
from app.risk_engine import RiskEngine
from app.state import OperationsState


@pytest.mark.asyncio
async def test_mqtt_outage_does_not_kill_pipeline_and_backlog_recovers(
    tmp_path: Path,
) -> None:
    settings = replace(
        Settings(),
        durable_queue_path=str(tmp_path / "outbox.sqlite3"),
        delivery_retry_base_s=0.01,
        delivery_retry_max_s=0.05,
        delivery_circuit_failure_threshold=5,
    )
    durable = DurableQueue(settings.durable_queue_path)
    attempts = 0

    def broker(topic: str, payload: dict, qos: int | None = None) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("fault-injected broker outage")
        assert topic == "ground/events"
        assert payload["id"] == "fault-event"
        assert qos == 2

    async def no_op(*args, **kwargs) -> None:
        return None

    pipeline = LayeredPipeline(
        settings,
        OperationsState(),
        EventEngine(),
        RiskEngine("UTC", 20, 6),
        no_op,
        no_op,
        no_op,
        no_op,
        lambda track: None,
        lambda event: None,
        lambda evidence: None,
        broker,
        durable,
    )
    await pipeline.start()
    try:
        pipeline.queue_transport("ground/events", {"id": "fault-event"})
        for _ in range(40):
            if durable.stats()["mqtt"]["pending"] == 0:
                break
            await asyncio.sleep(0.025)
        assert attempts == 3
        assert durable.stats()["mqtt"]["pending"] == 0
        assert all(pipeline.health()["workers"].values())
    finally:
        await pipeline.stop()
