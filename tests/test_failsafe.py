import time

from app.config import Settings
from app.failsafe import assess_fail_safe
from app.schemas import VisionMetrics
from app.state import OperationsState


def _pipeline_health() -> dict:
    return {
        "queues": {"ingress": 0, "rules": 0, "storage": 0, "egress": 0},
        "dropped": 0,
        "errors": {},
        "workers": {
            "fusion-layer": True,
            "rules-layer": True,
            "storage-layer": True,
            "egress-layer": True,
        },
    }


def test_stale_vision_activates_fail_safe() -> None:
    settings = Settings(vision_metrics_stale_s=2)
    state = OperationsState()
    state.record_vision_metrics(
        VisionMetrics(
            source="camera-01",
            timestamp=time.time() - 10,
            status="processing",
            model_name="test.pt",
            device="cpu",
            frames_captured=1,
            frames_inferred=1,
            frames_posted=1,
            frames_dropped_for_latency=0,
            capture_fps=30,
            inference_fps=30,
            last_detection_count=0,
        )
    )
    report = assess_fail_safe(
        settings,
        state,
        _pipeline_health(),
        mqtt_connected=True,
        storage_available=True,
        llm_health={"enabled": False},
        security_llm_health={"enabled": False},
    )
    assert report["fail_safe_active"] is True
    assert (
        next(item for item in report["layers"] if item["id"] == "video")["status"]
        == "failed"
    )


def test_optional_llm_does_not_fail_healthy_core() -> None:
    settings = Settings(vision_metrics_stale_s=5, enable_fall_detection=False)
    state = OperationsState()
    state.record_vision_metrics(
        VisionMetrics(
            source="camera-01",
            timestamp=time.time(),
            status="processing",
            model_name="test.pt",
            device="cuda:0",
            frames_captured=10,
            frames_inferred=10,
            frames_posted=10,
            frames_dropped_for_latency=0,
            capture_fps=30,
            inference_fps=30,
            last_detection_count=0,
        )
    )
    report = assess_fail_safe(
        settings,
        state,
        _pipeline_health(),
        mqtt_connected=True,
        storage_available=True,
        llm_health={"enabled": True, "worker": True, "circuit": {"state": "open"}},
        security_llm_health={"enabled": False},
    )
    assert report["critical_path_healthy"] is True
    assert (
        next(item for item in report["layers"] if item["id"] == "llm_object")["status"]
        == "degraded"
    )
