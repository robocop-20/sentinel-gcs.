import time

from app.resilience import CircuitBreaker


def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_s=0.01)
    assert breaker.allow_request()
    breaker.record_failure()
    assert breaker.health()["state"] == "closed"
    breaker.record_failure()
    assert breaker.health()["state"] == "open"
    assert not breaker.allow_request()
    time.sleep(0.02)
    assert breaker.allow_request()
    assert breaker.health()["state"] == "half_open"
    breaker.record_success()
    assert breaker.health()["state"] == "closed"
