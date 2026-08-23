from app.track_gate import TrackConfirmationGate


def test_track_requires_temporal_confirmation_before_publish():
    gate = TrackConfirmationGate(minimum_observations=3, maximum_gap_s=1.5)
    assert gate.observe("camera-01-T-007", 1.0) == (False, 1)
    assert gate.observe("camera-01-T-007", 1.2) == (False, 2)
    assert gate.observe("camera-01-T-007", 1.4) == (True, 3)


def test_stale_track_loses_confirmation_history():
    gate = TrackConfirmationGate(minimum_observations=2, maximum_gap_s=1.0)
    assert gate.observe("camera-01-T-007", 1.0) == (False, 1)
    assert gate.observe("camera-01-T-007", 2.1) == (False, 1)


def test_track_requires_stable_class_and_mean_confidence():
    gate = TrackConfirmationGate(
        minimum_observations=3,
        maximum_gap_s=1.0,
        evidence_window=4,
        minimum_class_stability=0.75,
    )
    assert gate.observe(
        "T-1", 1.0, class_name="person", confidence=0.55, minimum_mean_confidence=0.62
    ) == (False, 1)
    assert gate.observe(
        "T-1", 1.1, class_name="vehicle", confidence=0.80, minimum_mean_confidence=0.62
    ) == (False, 2)
    assert gate.observe(
        "T-1", 1.2, class_name="person", confidence=0.70, minimum_mean_confidence=0.62
    ) == (False, 3)
    assert gate.observe(
        "T-1", 1.3, class_name="person", confidence=0.70, minimum_mean_confidence=0.62
    ) == (True, 4)
    evidence = gate.evidence("T-1")
    assert evidence["class_stability"] == 0.75
    assert (
        evidence["mean_confidence"] is not None and evidence["mean_confidence"] >= 0.62
    )


def test_track_supports_class_specific_temporal_confirmation():
    gate = TrackConfirmationGate(minimum_observations=3, maximum_gap_s=1.0)
    for observation in range(4):
        assert gate.observe(
            "person-1",
            1 + observation / 10,
            class_name="person",
            confidence=0.8,
            minimum_mean_confidence=0.6,
            minimum_observations=5,
        )[0] is False
    assert gate.observe(
        "person-1",
        1.4,
        class_name="person",
        confidence=0.8,
        minimum_mean_confidence=0.6,
        minimum_observations=5,
    )[0] is True
