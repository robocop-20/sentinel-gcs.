import json

from app.config import Settings
from app.schemas import SecurityFinding
from app.security_adviser import SecurityAdviser


def finding() -> SecurityFinding:
    return SecurityFinding(
        id="finding-1",
        timestamp=1,
        source_id="mavlink-1",
        category="telemetry_integrity",
        code="gps_kinematic_jump",
        severity="critical",
        message="Position jump detected.",
        evidence={"latitude": 17.686, "raw_packet": "never-export"},
        recommended_action="Validate GNSS and telemetry.",
    )


def test_security_adviser_requires_separate_text_egress_consent():
    adviser = SecurityAdviser(
        Settings(
            enable_llm_security_advisory=True,
            llm_provider="google",
            llm_api_key="test-key",
        )
    )
    assert adviser.enabled is False


def test_security_adviser_payload_excludes_raw_evidence_fields():
    adviser = SecurityAdviser(
        Settings(
            enable_llm_security_advisory=True,
            enable_external_llm_text_egress=True,
            llm_provider="google",
            llm_api_key="test-key",
        )
    )
    body = adviser._body([finding()]).decode("utf-8")
    parsed = json.loads(body)
    assert "raw_packet" not in body
    assert "latitude" not in body
    assert parsed["generationConfig"]["responseMimeType"] == "application/json"
    assert parsed["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "low"
    assert parsed["generationConfig"]["maxOutputTokens"] == 512


def test_security_adviser_accepts_fenced_but_valid_json():
    summary, recommendations = SecurityAdviser._parse_content(
        '```json\n{"summary":"Review complete.","recommendations":["Check locally."]}\n```'
    )
    assert summary == "Review complete."
    assert recommendations == ["Check locally."]
