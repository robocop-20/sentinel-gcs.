from app.metrics import SentinelMetrics
from app.schemas import VisionMetrics


def test_metrics_expose_vision_latency_and_frame_deltas() -> None:
    metrics = SentinelMetrics()
    sample = VisionMetrics(
        source="camera-01",
        timestamp=1,
        status="processing",
        model_name="test-model",
        device="cpu",
        frames_captured=10,
        frames_inferred=8,
        frames_posted=8,
        frames_dropped_for_latency=2,
        capture_fps=30,
        inference_fps=20,
        last_inference_ms=40,
        last_end_to_end_ms=60,
        last_detection_count=1,
    )
    metrics.record_vision(sample)
    metrics.record_vision(sample.model_copy(update={"frames_captured": 12}))
    body, content_type = metrics.render()
    text = body.decode("utf-8")
    assert "sentinel_vision_end_to_end_latency_ms_bucket" in text
    assert 'sentinel_vision_frames_total{source="camera-01",stage="captured"} 12.0' in text
    assert "text/plain" in content_type
