from app.schemas import BBox, Detection, DetectionBatch, VisionMetrics


def test_detection_batch_preserves_identification_and_confidence_contract():
    batch = DetectionBatch(
        batch_id="550e8400-e29b-41d4-a716-446655440000",
        timestamp=10.2,
        captured_at=10.0,
        source="camera-01",
        frame_width=1920,
        frame_height=1080,
        model_name="yolo11s.pt",
        inference_ms=41.5,
        detections=[
            Detection(
                track_id="camera-01-T-007",
                **{"class": "vehicle"},
                model_class="truck",
                confidence=0.9132,
                bbox=BBox(x=1, y=2, width=3, height=4),
            )
        ],
    )
    assert batch.detections[0].class_name == "vehicle"
    assert batch.detections[0].model_class == "truck"
    assert batch.detections[0].confidence == 0.9132
    assert batch.batch_id == "550e8400-e29b-41d4-a716-446655440000"


def test_vision_metrics_has_non_negative_latency_contract():
    metrics = VisionMetrics(
        source="camera-01",
        timestamp=1,
        status="processing",
        model_name="yolo11s.pt",
        device="cpu",
        frames_captured=20,
        frames_inferred=8,
        frames_posted=8,
        frames_dropped_for_latency=12,
        capture_fps=30,
        inference_fps=12,
        last_inference_ms=80,
        last_end_to_end_ms=95,
        last_detection_count=2,
    )
    assert metrics.frames_dropped_for_latency == 12
