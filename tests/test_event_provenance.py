from dataclasses import replace

import pytest

from app.config import Settings
from app.durable_queue import DurableQueue
from app.events import EventEngine
from app.pipeline import LayeredPipeline
from app.risk_engine import RiskEngine
from app.schemas import Event, Location
from app.state import OperationsState


@pytest.mark.asyncio
async def test_local_event_receives_model_geofence_and_evidence_provenance(tmp_path):
    settings = replace(
        Settings(), durable_queue_path=str(tmp_path / "provenance.sqlite3")
    )
    state = OperationsState()
    state.tracks["track-1"] = {
        "track_id": "track-1",
        "source": "camera-01",
        "timestamp": 100.0,
        "captured_at": 99.9,
        "confidence": 0.81,
        "model_name": "port-yolo",
        "model_version": "2.1.0",
        "model_sha256": "a" * 64,
        "model_integrity_verified": True,
        "evidence": {"evidence_id": "evidence-1", "sha256": "b" * 64},
    }
    captured = []

    async def on_event(event):
        captured.append(event)

    async def no_op(*args, **kwargs):
        return None

    pipeline = LayeredPipeline(
        settings,
        state,
        EventEngine(),
        RiskEngine("UTC", 20, 6),
        no_op,
        no_op,
        on_event,
        no_op,
        lambda track: None,
        lambda event: None,
        lambda evidence: None,
        lambda topic, payload, qos=None: None,
        DurableQueue(settings.durable_queue_path),
    )
    event = Event(
        id="00000000-0000-0000-0000-000000000010",
        timestamp=100.0,
        event_type="geofence_entry",
        severity="critical",
        track_id="track-1",
        geofence_id=state.geofences[0].id,
        message="entry",
        location=Location(latitude=17.0, longitude=83.0),
    )
    await pipeline.dispatch_event(event, relay_v2x=False)

    provenance = captured[0].provenance
    assert provenance.detector_version == "2.1.0"
    assert provenance.detector_weights_sha256 == "a" * 64
    assert provenance.geofence_version.startswith("sha256:")
    assert provenance.evidence_sha256 == "b" * 64
