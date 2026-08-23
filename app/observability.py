"""Structured service logging and request-correlation primitives.

The formatter intentionally emits a small, stable JSON schema so logs from the
API and background workers can be shipped without exposing request bodies,
camera URLs, credentials, or image data.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_span_id: contextvars.ContextVar[str] = contextvars.ContextVar("span_id", default="")
_service_name = "sentinel"


def correlation_id() -> str:
    return _correlation_id.get()


def new_correlation_id(value: str | None = None) -> str:
    candidate = (value or "").strip()
    if (
        not candidate
        or len(candidate) > 128
        or not all(char.isalnum() or char in "-_.:" for char in candidate)
    ):
        candidate = str(uuid4())
    return candidate


def bind_correlation_id(value: str) -> contextvars.Token[str]:
    return _correlation_id.set(value)


def reset_correlation_id(token: contextvars.Token[str]) -> None:
    _correlation_id.reset(token)


def new_trace_context(traceparent: str | None = None) -> tuple[str, str]:
    """Accept W3C Trace Context when valid; always create a fresh local span."""
    trace = ""
    parts = (traceparent or "").strip().split("-")
    if (
        len(parts) == 4
        and parts[0] == "00"
        and len(parts[1]) == 32
        and parts[1] != "0" * 32
        and all(char in "0123456789abcdefABCDEF" for char in parts[1])
    ):
        trace = parts[1].lower()
    return trace or secrets.token_hex(16), secrets.token_hex(8)


def bind_trace_context(
    trace: str, span: str
) -> tuple[contextvars.Token[str], contextvars.Token[str]]:
    return _trace_id.set(trace), _span_id.set(span)


def reset_trace_context(
    tokens: tuple[contextvars.Token[str], contextvars.Token[str]],
) -> None:
    _trace_id.reset(tokens[0])
    _span_id.reset(tokens[1])


def current_traceparent() -> str:
    trace, span = _trace_id.get(), _span_id.get()
    return f"00-{trace}-{span}-01" if trace and span else ""


class JsonFormatter(logging.Formatter):
    """One-line JSON logs suitable for ingestion by Loki, ELK, or a SIEM."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "service": _service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = correlation_id()
        if request_id:
            payload["correlation_id"] = request_id
        trace = _trace_id.get()
        span = _span_id.get()
        if trace:
            payload["trace_id"] = trace
        if span:
            payload["span_id"] = span
        for key in (
            "event",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "component",
            "record_id",
            "attempt",
            "attempts",
            "retry_delay_s",
            "topic",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__
                if record.exc_info[0]
                else "Exception",
                "message": str(record.exc_info[1])[:500] if record.exc_info[1] else "",
            }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_logging(service_name: str, level: str | None = None) -> None:
    """Configure the process once; no secret-bearing application data is added."""
    global _service_name
    _service_name = service_name
    selected_level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, selected_level, logging.INFO))
    # Uvicorn access output is replaced by the correlation middleware log.
    logging.getLogger("uvicorn.access").disabled = True


class RequestTimer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 3)
