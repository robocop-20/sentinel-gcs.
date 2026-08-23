"""Optional text-only LLM summaries of deterministic security findings.

No imagery, face data, GPS coordinates, raw telemetry packets, credentials, or
network payloads leave the ground station through this component.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from .config import Settings
from .llm_verifier import GEMINI_URL, OPENROUTER_URL, XAI_URL
from .resilience import CircuitBreaker, is_transient_provider_error
from .schemas import SecurityAdvisory, SecurityFinding

LOGGER = logging.getLogger(__name__)


class SecurityAdviser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last_outcome: str | None = None
        self.last_latency_ms: float | None = None
        self.last_attempts = 0

    @property
    def provider(self) -> str:
        return self.settings.llm_provider.strip().lower()

    @property
    def model_name(self) -> str:
        if self.provider in {
            "google",
            "gemini",
        } and self.settings.llm_model.strip().lower() in {"", "gemini"}:
            return "gemini-3.6-flash"
        return self.settings.llm_model

    @property
    def enabled(self) -> bool:
        return (
            self.settings.enable_llm_security_advisory
            and self.settings.enable_external_llm_text_egress
            and self.provider in {"openrouter", "xai", "grok", "google", "gemini"}
            and bool(self.settings.llm_api_key.strip())
        )

    @staticmethod
    def _sanitised_findings(findings: list[SecurityFinding]) -> list[dict[str, object]]:
        return [
            {
                "id": finding.id,
                "source": finding.source_id,
                "category": finding.category,
                "code": finding.code,
                "severity": finding.severity,
                "message": finding.message,
                "recommended_action": finding.recommended_action,
            }
            for finding in findings[-8:]
        ]

    @staticmethod
    def _parse_content(content: object) -> tuple[str, list[str]]:
        """Accept provider JSON or a fenced JSON object, then validate fields."""
        if not isinstance(content, str):
            raise ValueError("missing structured security summary")
        text = content.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("missing structured security summary")
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError("invalid structured security summary") from exc
        summary = parsed.get("summary") if isinstance(parsed, dict) else None
        recommendations = (
            parsed.get("recommendations") if isinstance(parsed, dict) else None
        )
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("missing structured security summary")
        safe_recommendations = (
            [
                item[:300]
                for item in recommendations
                if isinstance(item, str) and item.strip()
            ]
            if isinstance(recommendations, list)
            else []
        )
        return summary, safe_recommendations

    def _body(self, findings: list[SecurityFinding]) -> bytes:
        evidence = json.dumps(self._sanitised_findings(findings), separators=(",", ":"))
        prompt = (
            "Summarise these deterministic defensive security or physical-safety findings for an operator. "
            "Do not invent facts, identify people, propose offensive activity, or issue commands. "
            "Return JSON only with summary and recommendations (maximum three short defensive recommendations). "
            f"Findings: {evidence}"
        )
        system = "You are a constrained defensive security incident adviser. Your output is advisory only."
        properties = {
            "summary": {"type": "string"},
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
        }
        if self.provider in {"google", "gemini"}:
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 512,
                    "thinkingConfig": {"thinkingLevel": "low"},
                    "responseMimeType": "application/json",
                    "responseSchema": {
                        "type": "object",
                        "properties": properties,
                        "required": ["summary", "recommendations"],
                    },
                },
            }
        else:
            payload = {
                "model": self.model_name,
                "temperature": 0,
                "max_tokens": 220,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "security_advisory",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": properties,
                            "required": ["summary", "recommendations"],
                        },
                    },
                },
            }
        return json.dumps(payload).encode("utf-8")

    def _endpoint(self) -> str:
        if self.provider in {"xai", "grok"}:
            return XAI_URL
        if self.provider in {"google", "gemini"}:
            return f"{GEMINI_URL}/{urllib.parse.quote(self.model_name, safe='-._')}:generateContent"
        return OPENROUTER_URL

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.provider in {"google", "gemini"}:
            headers["x-goog-api-key"] = self.settings.llm_api_key
        else:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        return headers

    def _result(
        self,
        findings: list[SecurityFinding],
        status: str,
        summary: str,
        recommendations: list[str] | None = None,
    ) -> SecurityAdvisory:
        return SecurityAdvisory(
            request_id=str(uuid4()),
            finding_ids=[finding.id for finding in findings[-8:]],
            provider=f"{self.provider}:{self.model_name}",
            reviewed_at=time.time(),
            status=status,
            summary=summary[:1000],
            recommendations=(recommendations or [])[:3],
        )

    def advise(self, findings: list[SecurityFinding]) -> SecurityAdvisory:
        started = time.monotonic()
        self.last_attempts = 0
        if not self.enabled:
            self.last_outcome = "configuration_unavailable"
            self.last_latency_ms = (time.monotonic() - started) * 1000
            return self._result(
                findings,
                "unavailable",
                "Security LLM advisory or explicit text-egress consent is unavailable.",
            )
        retry_count = max(self.settings.llm_max_retries, 0)
        body = self._body(findings)
        for attempt in range(retry_count + 1):
            self.last_attempts = attempt + 1
            request = urllib.request.Request(
                self._endpoint(), data=body, method="POST", headers=self._headers()
            )
            try:
                # Endpoint selection is an internal provider allowlist in _endpoint().
                with urllib.request.urlopen(  # nosec B310
                    request, timeout=self.settings.llm_request_timeout_s
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if self.provider in {"google", "gemini"}:
                    content = payload["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    content = payload["choices"][0]["message"]["content"]
                summary, safe_recommendations = self._parse_content(content)
                self.last_outcome = "success"
                self.last_latency_ms = (time.monotonic() - started) * 1000
                return self._result(
                    findings, "available", summary, safe_recommendations
                )
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                ConnectionError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                transient = is_transient_provider_error(exc)
                if transient and attempt < retry_count:
                    time.sleep(max(self.settings.llm_retry_backoff_s, 0) * (2**attempt))
                    continue
                LOGGER.warning(
                    "%s security advisory unavailable: %s",
                    self.provider,
                    type(exc).__name__,
                )
                self.last_outcome = "provider_error"
                self.last_latency_ms = (time.monotonic() - started) * 1000
                return self._result(
                    findings,
                    "unavailable",
                    "External security advisory was unavailable.",
                )
        raise RuntimeError("unreachable provider retry state")


class SecurityAdvisoryWorker:
    """Latest-only background text queue; never delays integrity rules."""

    def __init__(self, settings: Settings, on_advisory) -> None:
        self.adviser = SecurityAdviser(settings)
        self.on_advisory = on_advisory
        self.queue: asyncio.Queue[list[SecurityFinding]] = asyncio.Queue(maxsize=1)
        self.task: asyncio.Task | None = None
        self.dropped = 0
        self.completed = 0
        self.provider_failures = 0
        self.circuit_rejected = 0
        self.last_status: str | None = None
        self.breaker = CircuitBreaker(
            settings.llm_circuit_failure_threshold, settings.llm_circuit_cooldown_s
        )

    @property
    def enabled(self) -> bool:
        return self.adviser.enabled

    async def start(self) -> None:
        if self.enabled:
            self.task = asyncio.create_task(
                self._run(), name="security-llm-advisory-layer"
            )

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def submit(self, findings: list[SecurityFinding]) -> bool:
        if not self.enabled or not findings:
            return False
        try:
            self.queue.put_nowait(findings[-8:])
            return True
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                LOGGER.debug("Security advisory queue drained during replacement")
            self.dropped += 1
            self.queue.put_nowait(findings[-8:])
            return True

    def health(self) -> dict:
        key_configured = bool(self.adviser.settings.llm_api_key.strip())
        disabled_reasons = []
        if not self.adviser.settings.enable_llm_security_advisory:
            disabled_reasons.append("security advisory disabled")
        if not self.adviser.settings.enable_external_llm_text_egress:
            disabled_reasons.append("external text egress not approved")
        if not key_configured:
            disabled_reasons.append("selected provider key missing")
        return {
            "enabled": self.enabled,
            "worker": bool(self.task and not self.task.done()),
            "queued": self.queue.qsize(),
            "queue_capacity": self.queue.maxsize,
            "dropped": self.dropped,
            "completed": self.completed,
            "last_status": self.last_status,
            "provider_failures": self.provider_failures,
            "circuit_rejected": self.circuit_rejected,
            "last_latency_ms": self.adviser.last_latency_ms,
            "last_attempts": self.adviser.last_attempts,
            "circuit": self.breaker.health(),
            "retry_policy": {
                "max_retries": self.adviser.settings.llm_max_retries,
                "base_backoff_s": self.adviser.settings.llm_retry_backoff_s,
                "request_timeout_s": self.adviser.settings.llm_request_timeout_s,
            },
            "external_text_egress_approved": self.adviser.settings.enable_external_llm_text_egress,
            "provider": self.adviser.provider,
            "model": self.adviser.model_name,
            "key_configured": key_configured,
            "supported_providers": ["openrouter", "xai", "google"],
            "disabled_reasons": disabled_reasons,
            "automatic_actions": False,
        }

    async def _run(self) -> None:
        while True:
            findings = await self.queue.get()
            try:
                if not self.breaker.allow_request():
                    self.circuit_rejected += 1
                    advisory = self.adviser._result(
                        findings,
                        "unavailable",
                        "External advisory circuit is open; local findings remain authoritative.",
                    )
                else:
                    advisory = await asyncio.to_thread(self.adviser.advise, findings)
                    if self.adviser.last_outcome == "success":
                        self.breaker.record_success()
                    elif self.adviser.last_outcome == "provider_error":
                        self.provider_failures += 1
                        self.breaker.record_failure()
                self.completed += 1
                self.last_status = advisory.status
                await self.on_advisory(advisory)
            except Exception:
                LOGGER.exception(
                    "Security LLM advisory failed without affecting integrity monitoring"
                )
            finally:
                self.queue.task_done()
