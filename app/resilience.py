"""Small fault-isolation primitives shared by optional external services."""

from __future__ import annotations

import time
import urllib.error
from dataclasses import dataclass


def is_transient_provider_error(exc: BaseException) -> bool:
    """Retry only rate limits, provider/server faults, timeouts and link faults."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or 500 <= exc.code < 600
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


@dataclass
class CircuitBreaker:
    """Single-worker circuit breaker; it never affects the core safety path."""

    failure_threshold: int = 3
    cooldown_s: float = 60.0
    failures: int = 0
    state: str = "closed"
    opened_at: float | None = None
    _opened_monotonic: float | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None

    def allow_request(self) -> bool:
        if self.state != "open":
            return True
        if (
            self._opened_monotonic is None
            or time.monotonic() - self._opened_monotonic < self.cooldown_s
        ):
            return False
        self.state = "half_open"
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"
        self.opened_at = None
        self._opened_monotonic = None
        self.last_success_at = time.time()

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_at = time.time()
        if self.state == "half_open" or self.failures >= max(self.failure_threshold, 1):
            self.state = "open"
            self.opened_at = time.time()
            self._opened_monotonic = time.monotonic()

    def health(self) -> dict[str, object]:
        display_state = self.state
        retry_after_s = 0.0
        if self.state == "open" and self._opened_monotonic is not None:
            elapsed = time.monotonic() - self._opened_monotonic
            retry_after_s = max(0.0, self.cooldown_s - elapsed)
            if retry_after_s == 0:
                display_state = "half_open"
        return {
            "state": display_state,
            "consecutive_failures": self.failures,
            "failure_threshold": max(self.failure_threshold, 1),
            "retry_after_s": round(retry_after_s, 3),
            "opened_at": self.opened_at,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
        }
