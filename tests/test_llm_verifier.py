import base64

from app.config import Settings
from app.llm_verifier import VisionVerifier
from app.schemas import EvidenceRequest, Location


def request_without_crop() -> EvidenceRequest:
    return EvidenceRequest(
        request_id="request-1",
        event_id="event-1",
        track_id="track-1",
        requested_at=1,
        expires_at=60,
        reason="Advisory visual verification",
        location=Location(latitude=17.68, longitude=83.21),
    )


def test_verifier_without_permitted_crop_never_makes_a_network_call(tmp_path):
    key_file = tmp_path / "evidence-key"
    key_file.write_text(
        base64.urlsafe_b64encode(b"x" * 32).decode("ascii"), encoding="utf-8"
    )
    verifier = VisionVerifier(
        Settings(
            enable_llm_verification=True,
            enable_external_llm_egress=True,
            llm_api_key="test-key",
            evidence_encryption_key_file=str(key_file),
        )
    )
    result = verifier.verify(request_without_crop())
    assert result.advisory_only is True
    assert result.verdict == "unavailable"
    assert "crop" in result.rationale.lower()


def test_unstructured_provider_answer_is_never_treated_as_confirmation():
    assert VisionVerifier._parse_review("not json") == (
        "inconclusive",
        "Provider returned an unstructured review.",
    )


def test_xai_request_is_structured_and_prohibits_biometric_matching():
    verifier = VisionVerifier(
        Settings(
            enable_llm_verification=True,
            llm_provider="xai",
            llm_model="grok-4.5",
            llm_api_key="test-key",
        )
    )
    body = verifier._request_body(
        "data:image/jpeg;base64,AA==", request_without_crop()
    ).decode("utf-8")
    assert '"store": false' in body
    assert '"response_format"' in body
    assert "face matching" in body


def test_key_does_not_enable_external_image_egress_without_separate_consent():
    verifier = VisionVerifier(
        Settings(
            enable_llm_verification=True, llm_provider="xai", llm_api_key="test-key"
        )
    )
    assert verifier.enabled is False


def test_google_gemini_adapter_uses_inline_image_and_structured_json():
    verifier = VisionVerifier(
        Settings(llm_provider="google", llm_model="gemini", llm_api_key="test-key")
    )
    body = verifier._request_body(
        "data:image/jpeg;base64,AA==", request_without_crop()
    ).decode("utf-8")
    assert '"inline_data"' in body
    assert '"responseMimeType": "application/json"' in body
    assert '"thinkingLevel": "low"' in body
    assert '"maxOutputTokens": 512' in body
    assert verifier.model_name == "gemini-3.6-flash"
    assert verifier._endpoint().endswith("gemini-3.6-flash:generateContent")
