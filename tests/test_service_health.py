import json
from urllib.error import HTTPError
from urllib.request import urlopen

from app.service_health import ServiceHealth


def test_worker_health_liveness_and_readiness() -> None:
    health = ServiceHealth("test-worker", 0)
    health.start()
    try:
        with urlopen(f"http://127.0.0.1:{health.port}/healthz", timeout=2) as response:
            assert json.load(response)["status"] == "alive"
        try:
            urlopen(f"http://127.0.0.1:{health.port}/readyz", timeout=2)
            raise AssertionError("not-ready worker returned success")
        except HTTPError as exc:
            assert exc.code == 503
        health.set_ready(True, stage="processing")
        with urlopen(f"http://127.0.0.1:{health.port}/readyz", timeout=2) as response:
            assert json.load(response)["details"]["stage"] == "processing"
    finally:
        health.stop()
