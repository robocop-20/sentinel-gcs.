from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from .schemas import Detection, Event


@dataclass(frozen=True)
class RiskAssessment:
    score: int
    severity: str
    factors: list[str]


class RiskEngine:
    """Transparent, deterministic risk scoring; no identity or opaque AI score."""

    def __init__(
        self, timezone_name: str, quiet_start_hour: int, quiet_end_hour: int
    ) -> None:
        self.timezone = ZoneInfo(timezone_name)
        self.quiet_start_hour = quiet_start_hour
        self.quiet_end_hour = quiet_end_hour

    def assess(
        self, detection: Detection, is_restricted: bool, timestamp: float
    ) -> RiskAssessment:
        score = 0
        factors = [f"object:{detection.class_name}"]
        if detection.class_name == "person":
            score += 35
        elif detection.class_name in {"vessel", "vehicle"}:
            score += 30
        if detection.confidence >= 0.75:
            score += 10
            factors.append("high_detection_confidence")
        if is_restricted:
            score += 40
            factors.append("restricted_geofence")
        local_hour = datetime.fromtimestamp(timestamp, self.timezone).hour
        is_quiet = (
            local_hour >= self.quiet_start_hour or local_hour < self.quiet_end_hour
        )
        if is_quiet:
            score += 15
            factors.append("quiet_hours")
        score = min(score, 100)
        severity = "critical" if score >= 75 else "warning" if score >= 45 else "info"
        return RiskAssessment(score=score, severity=severity, factors=factors)

    @staticmethod
    def apply(event: Event, assessment: RiskAssessment) -> Event:
        event.risk_score = assessment.score
        event.risk_factors = assessment.factors
        event.severity = assessment.severity
        return event
