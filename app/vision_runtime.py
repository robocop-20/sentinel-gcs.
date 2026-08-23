"""Low-latency runtime primitives for the live perception adapter.

Capture and HTTP delivery are deliberately outside the inference loop.  Each
boundary keeps only its newest item, so a slow model, API, database, or MQTT
service cannot cause the worker to analyse seconds-old video.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from .service_auth import ServiceTokenProvider

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    captured_at: float
    frame: Any


class LatestFrameCapture:
    """Continuously read a source and expose just the newest complete frame."""

    def __init__(
        self,
        open_capture: Callable[[], Any],
        reconnect_delay_s: float,
        reconnect_max_delay_s: float = 15.0,
    ) -> None:
        self._open_capture = open_capture
        self._reconnect_delay_s = max(reconnect_delay_s, 0.1)
        self._reconnect_max_delay_s = max(
            reconnect_max_delay_s, self._reconnect_delay_s
        )
        self._reconnect_attempts = 0
        self._current_reconnect_delay_s = self._reconnect_delay_s
        self._latest: CapturedFrame | None = None
        self._sequence = 0
        self._frames_captured = 0
        self._frames_replaced = 0
        self._last_error: str | None = None
        self._condition = threading.Condition()
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="vision-capture", daemon=True
        )
        self._metrics_at = time.monotonic()
        self._metrics_frames = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        with self._condition:
            self._condition.notify_all()
        self._thread.join(timeout=3)

    def next_after(self, sequence: int, timeout_s: float = 1.0) -> CapturedFrame | None:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while not self._stopped.is_set() and (
                self._latest is None or self._latest.sequence <= sequence
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return (
                self._latest
                if self._latest and self._latest.sequence > sequence
                else None
            )

    def metrics(self) -> dict[str, int | float | str | None]:
        with self._condition:
            now = time.monotonic()
            elapsed = max(now - self._metrics_at, 0.001)
            recent_frames = self._frames_captured - self._metrics_frames
            self._metrics_at = now
            self._metrics_frames = self._frames_captured
            return {
                "frames_captured": self._frames_captured,
                "frames_replaced": self._frames_replaced,
                "capture_fps": recent_frames / elapsed,
                "last_error": self._last_error,
                "reconnect_attempts": self._reconnect_attempts,
                "reconnect_delay_s": self._current_reconnect_delay_s,
            }

    def _record_reconnect_failure(self) -> float:
        self._reconnect_attempts += 1
        self._current_reconnect_delay_s = min(
            self._reconnect_delay_s * (2 ** min(self._reconnect_attempts - 1, 10)),
            self._reconnect_max_delay_s,
        )
        return self._current_reconnect_delay_s

    def _record_frame_success(self) -> None:
        self._reconnect_attempts = 0
        self._current_reconnect_delay_s = self._reconnect_delay_s

    def _run(self) -> None:
        stream = None
        while not self._stopped.is_set():
            if stream is None:
                try:
                    stream = self._open_capture()
                    if not stream.isOpened():
                        raise RuntimeError(
                            "OpenCV could not open the configured video source"
                        )
                    with self._condition:
                        self._last_error = None
                except Exception as exc:
                    with self._condition:
                        self._last_error = str(exc)
                    if stream is not None:
                        stream.release()
                        stream = None
                    self._stopped.wait(self._record_reconnect_failure())
                    continue
            ok, frame = stream.read()
            if not ok:
                with self._condition:
                    self._last_error = "Video source returned no frame; reconnecting"
                stream.release()
                stream = None
                self._stopped.wait(self._record_reconnect_failure())
                continue
            with self._condition:
                self._record_frame_success()
                if self._latest is not None:
                    self._frames_replaced += 1
                self._sequence += 1
                self._frames_captured += 1
                self._latest = CapturedFrame(self._sequence, time.time(), frame)
                self._condition.notify_all()
        if stream is not None:
            stream.release()


class LatestApiPublisher:
    """Asynchronously POST only the most recent detection batch and metrics."""

    def __init__(
        self,
        api_url: str,
        timeout_s: float,
        client_id: str = "",
        client_secret_file: str = "",
        ca_cert: str = "",
        client_cert: str = "",
        client_key: str = "",
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s
        self._detections: queue.Queue[dict] = queue.Queue(maxsize=1)
        self._metrics: queue.Queue[dict] = queue.Queue(maxsize=1)
        self._preview: queue.Queue[dict] = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="vision-api-publisher", daemon=True
        )
        self._lock = threading.Lock()
        self._frames_posted = 0
        self._frames_replaced = 0
        self._last_error: str | None = None
        self._token_provider = ServiceTokenProvider(
            self._api_url,
            client_id,
            client_secret_file,
            timeout_s=max(timeout_s, 1.0),
            ca_cert=ca_cert,
            client_cert=client_cert,
            client_key=client_key,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    def submit_detections(self, payload: dict) -> None:
        self._replace_latest(self._detections, payload, detection=True)

    def submit_metrics(self, payload: dict) -> None:
        self._replace_latest(self._metrics, payload, detection=False)

    def submit_preview(self, payload: dict) -> None:
        # Visual telemetry only; never blocks the inference loop.
        self._replace_latest(self._preview, payload, detection=False)

    def metrics(self) -> dict[str, int | str | None]:
        with self._lock:
            return {
                "frames_posted": self._frames_posted,
                "frames_replaced": self._frames_replaced,
                "last_error": self._last_error,
            }

    def _replace_latest(
        self, target: queue.Queue[dict], payload: dict, detection: bool
    ) -> None:
        try:
            target.put_nowait(payload)
        except queue.Full:
            try:
                target.get_nowait()
            except queue.Empty:
                LOGGER.debug("Latest-item queue drained during replacement")
            target.put_nowait(payload)
            if detection:
                with self._lock:
                    self._frames_replaced += 1

    def _next_payload(self) -> tuple[str, dict] | None:
        try:
            # Metrics are emitted only every few seconds. Send one promptly so
            # sustained high frame rate cannot starve observability forever.
            return "/api/vision/metrics", self._metrics.get_nowait()
        except queue.Empty:
            try:
                return "/api/detections", self._detections.get(timeout=0.05)
            except queue.Empty:
                try:
                    return "/api/vision/preview", self._preview.get(timeout=0.05)
                except queue.Empty:
                    return None

    def _run(self) -> None:
        with requests.Session() as session:
            self._token_provider.configure_session(session)
            while not self._stop.is_set():
                next_item = self._next_payload()
                if next_item is None:
                    continue
                path, payload = next_item
                try:
                    headers = self._token_provider.authorization_header()
                    trace_key = payload.get("batch_id") or (
                        f"vision:{payload.get('source', 'unknown')}:"
                        f"{payload.get('timestamp', 0)}"
                    )
                    headers["X-Correlation-ID"] = str(trace_key)[:128]
                    trace_material = str(trace_key).encode("utf-8")
                    trace_id = hashlib.sha256(trace_material).hexdigest()[:32]
                    span_id = hashlib.sha256(trace_material + b":vision").hexdigest()[:16]
                    headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
                    response = session.post(
                        f"{self._api_url}{path}",
                        json=payload,
                        headers=headers,
                        timeout=self._timeout_s,
                    )
                    if response.status_code == 401 and self._token_provider.configured:
                        self._token_provider.invalidate()
                        response = session.post(
                            f"{self._api_url}{path}",
                            json=payload,
                            headers=self._token_provider.authorization_header(),
                            timeout=self._timeout_s,
                        )
                    response.raise_for_status()
                    with self._lock:
                        self._last_error = None
                        if path == "/api/detections":
                            self._frames_posted += 1
                except (
                    OSError,
                    RuntimeError,
                    KeyError,
                    requests.RequestException,
                ) as exc:
                    with self._lock:
                        self._last_error = f"{type(exc).__name__}: {exc}"
