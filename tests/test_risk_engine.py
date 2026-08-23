from app.risk_engine import RiskEngine
from app.schemas import BBox, Detection


def detection(object_class="person", confidence=0.9):
    return Detection(
        track_id="T-1",
        **{"class": object_class},
        confidence=confidence,
        bbox=BBox(x=1, y=1, width=2, height=2),
    )


def test_restricted_person_is_critical_risk():
    result = RiskEngine("UTC", 20, 6).assess(
        detection(), is_restricted=True, timestamp=1_700_000_000
    )
    assert result.score >= 75
    assert result.severity == "critical"


def test_unrestricted_low_confidence_vehicle_is_not_critical():
    result = RiskEngine("UTC", 20, 6).assess(
        detection("vehicle", 0.4), is_restricted=False, timestamp=1_700_000_000
    )
    assert result.severity != "critical"
