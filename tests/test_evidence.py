from app.config import Settings
from app.evidence import create_detection_advisory_request, create_evidence_request
from app.schemas import Event, Location


def test_high_risk_local_event_creates_advisory_evidence_request_only():
    settings = Settings(
        enable_llm_verification=True,
        llm_verification_min_risk=75,
        evidence_request_ttl_s=60,
        evidence_camera_ids="camera-02,camera-03",
    )
    event = Event(
        id="00000000-0000-0000-0000-000000000011",
        timestamp=10,
        event_type="geofence_entry",
        severity="critical",
        track_id="T-1",
        geofence_id="zone-a",
        message="entry",
        location=Location(latitude=17.68, longitude=83.21),
        risk_score=80,
        risk_factors=["restricted_geofence"],
    )
    request = create_evidence_request(
        settings,
        event,
        {
            "source": "camera-01",
            "class": "vehicle",
            "confidence": 0.9,
            "evidence_ref": "/evidence/camera-01-T-001.jpg",
        },
        None,
    )
    assert request is not None
    assert request.advisory_only is True
    assert request.requested_camera_ids == ["camera-02", "camera-03"]
    assert request.evidence_ref == "/evidence/camera-01-T-001.jpg"
    assert event.severity == "critical"


def test_confirmed_non_person_can_request_a_rate_limited_advisory_crop_review():
    settings = Settings(
        enable_llm_verification=True,
        enable_llm_detection_advisory=True,
        llm_advisory_min_confidence=0.60,
    )
    request = create_detection_advisory_request(
        settings,
        {
            "track_id": "camera-01-T-008",
            "class": "vehicle",
            "confidence": 0.81,
            "source": "camera-01",
            "timestamp": 10,
            "evidence_ref": "/evidence/camera-01-T-008.jpg",
            "location": None,
        },
    )
    assert request is not None
    assert request.advisory_only is True
    assert request.object_type == "vehicle"
    assert request.location is None


def test_detection_advisory_never_accepts_a_person_crop():
    settings = Settings(
        enable_llm_verification=True, enable_llm_detection_advisory=True
    )
    request = create_detection_advisory_request(
        settings,
        {
            "track_id": "camera-01-T-009",
            "class": "person",
            "confidence": 0.99,
            "source": "camera-01",
            "timestamp": 10,
            "evidence_ref": "/evidence/camera-01-T-009.jpg",
        },
    )
    assert request is None
