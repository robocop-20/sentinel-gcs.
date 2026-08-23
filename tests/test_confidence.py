from app.confidence import TrackConfidenceSmoother


def test_confidence_smoothing_is_track_specific_and_does_not_mutate_raw_input():
    smoother = TrackConfidenceSmoother(alpha=0.25, ttl_s=30)
    assert smoother.update("T-1", 0.8, 1) == 0.8
    assert smoother.update("T-1", 0.4, 2) == 0.7
    assert smoother.update("T-2", 0.4, 2) == 0.4
