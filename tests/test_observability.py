import json
import logging

from app.observability import (
    JsonFormatter,
    bind_correlation_id,
    bind_trace_context,
    current_traceparent,
    new_correlation_id,
    new_trace_context,
    reset_correlation_id,
    reset_trace_context,
)


def test_json_log_includes_correlation_id() -> None:
    request_id = new_correlation_id("mission-42")
    token = bind_correlation_id(request_id)
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "ready", (), None)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_correlation_id(token)
    assert payload["message"] == "ready"
    assert payload["correlation_id"] == "mission-42"


def test_invalid_correlation_id_is_replaced() -> None:
    assert new_correlation_id("bad value with spaces") != "bad value with spaces"


def test_w3c_trace_context_is_validated_and_logged() -> None:
    upstream = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    trace, span = new_trace_context(upstream)
    tokens = bind_trace_context(trace, span)
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "trace", (), None)
        payload = json.loads(JsonFormatter().format(record))
        traceparent = current_traceparent()
    finally:
        reset_trace_context(tokens)
    assert payload["trace_id"] == "0123456789abcdef0123456789abcdef"
    assert traceparent.startswith("00-0123456789abcdef0123456789abcdef-")
