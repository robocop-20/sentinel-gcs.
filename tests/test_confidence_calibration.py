import pytest

from training.analyze_confidence import analyze_records


def test_confidence_calibration_measures_ece_and_per_class():
    report = analyze_records(
        [
            {"confidence": 0.9, "correct": 1, "class": "person"},
            {"confidence": 0.8, "correct": 1, "class": "person"},
            {"confidence": 0.8, "correct": 0, "class": "vehicle"},
            {"confidence": 0.2, "correct": 0, "class": "vehicle"},
        ],
        bins=5,
    )
    assert report["prediction_count"] == 4
    assert report["expected_calibration_error"] == pytest.approx(0.175)
    assert report["per_class"]["person"]["empirical_precision"] == 1.0
    assert report["per_class"]["vehicle"]["empirical_precision"] == 0.0


def test_confidence_calibration_rejects_empty_input():
    with pytest.raises(ValueError, match="at least one"):
        analyze_records([], bins=10)
