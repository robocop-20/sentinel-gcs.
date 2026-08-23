from app.state import OperationsState
from app.schemas import V2XHeartbeat


def test_expiring_live_tracks_preserves_recent_tracks_only():
    state = OperationsState(active_track_ttl_s=8)
    state.tracks = {
        "old": {"timestamp": 10, "source": "camera-01"},
        "recent": {"timestamp": 19, "source": "camera-01"},
        "other": {"timestamp": 10, "source": "camera-02"},
    }
    state.track_persisted_at = {"old": 10, "recent": 19, "other": 10}

    assert state.expire_tracks(20, source="camera-01") == ["old"]
    assert set(state.tracks) == {"recent", "other"}
    assert set(state.track_persisted_at) == {"recent", "other"}


def test_v2x_device_registry_enforces_sequence_and_marks_stale_peer_offline():
    state = OperationsState(v2x_device_offline_s=10)
    heartbeat = V2XHeartbeat(
        message_id="heartbeat-0001",
        device_id="drone-01",
        device_type="drone",
        sent_at=100,
        sequence=8,
        capabilities=["event-receiver"],
        signature="signed",
    )
    assert state.record_v2x_heartbeat(heartbeat, received_at=100) is not None
    assert state.record_v2x_heartbeat(heartbeat, received_at=101) is None
    assert state.v2x_device_snapshot(now=105)[0]["link_status"] == "online"
    assert state.v2x_device_snapshot(now=111)[0]["link_status"] == "offline"


def test_anonymous_track_lifecycle_reports_occlusion_loss_and_reacquisition():
    state = OperationsState(
        active_track_ttl_s=8,
        track_occluded_after_s=1,
        track_temporarily_lost_after_s=3,
        track_reacquired_after_s=1,
    )
    assert state.record_track({"track_id": "T-1", "timestamp": 10})[
        "lifecycle_state"
    ] == "NEW"
    assert state.track_snapshot(now=11.2)[0]["lifecycle_state"] == "OCCLUDED"
    assert state.track_snapshot(now=13.2)[0]["lifecycle_state"] == (
        "TEMPORARILY_LOST"
    )
    assert state.record_track({"track_id": "T-1", "timestamp": 14})[
        "lifecycle_state"
    ] == "REACQUIRED"
    assert state.record_track({"track_id": "T-1", "timestamp": 14.2})[
        "lifecycle_state"
    ] == "ACTIVE"
