from app.motion import TrackMotionEstimator


def test_track_motion_reports_movement_and_image_heading():
    estimator = TrackMotionEstimator(moving_threshold_px_s=10, ttl_s=3)
    first = estimator.observe("camera-01-T-007", 0, 0, 100, 100, 1)
    second = estimator.observe("camera-01-T-007", 30, 0, 130, 100, 2)
    assert first["status"] == "unknown"
    assert second["status"] == "moving"
    assert second["speed_image_px_s"] == 30
    assert second["image_heading_deg"] == 90


def test_track_motion_expires_stale_track_state():
    estimator = TrackMotionEstimator(moving_threshold_px_s=10, ttl_s=1)
    estimator.observe("camera-01-T-007", 0, 0, 100, 100, 1)
    result = estimator.observe("camera-01-T-007", 50, 0, 150, 100, 3)
    assert result["status"] == "unknown"
