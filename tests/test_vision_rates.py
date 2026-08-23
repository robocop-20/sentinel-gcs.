from collections import deque

from app.vision_worker import _recent_inference_fps


def test_recent_inference_rate_ignores_old_downtime() -> None:
    timestamps = deque([100.0, 100.1, 100.2, 100.3])
    assert 9.9 < _recent_inference_fps(timestamps, 100.3) < 10.1
    assert _recent_inference_fps(timestamps, 110.0) == 0.0
    assert not timestamps
