"""Low-cardinality Prometheus instrumentation for engineering operations."""

from __future__ import annotations

import threading
import time
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from .schemas import Event, EvidenceVerification, VisionMetrics


LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)
INFERENCE_BUCKETS_MS = (5, 10, 20, 33, 50, 75, 100, 150, 250, 500, 1000)


class SentinelMetrics:
    """Own registry avoids collisions when API modules are loaded in tests."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._vision_previous: dict[str, dict[str, int]] = {}
        self._seen_tracks: dict[str, float] = {}

        self.http_requests = Counter(
            "sentinel_http_requests_total",
            "HTTP requests completed by route and status",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.http_latency = Histogram(
            "sentinel_http_request_duration_seconds",
            "HTTP request duration by route",
            ("method", "route"),
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.inference_latency = Histogram(
            "sentinel_vision_inference_latency_ms",
            "Reported model inference latency samples",
            ("source",),
            buckets=INFERENCE_BUCKETS_MS,
            registry=self.registry,
        )
        self.end_to_end_latency = Histogram(
            "sentinel_vision_end_to_end_latency_ms",
            "Frame capture to API delivery latency samples",
            ("source",),
            buckets=INFERENCE_BUCKETS_MS,
            registry=self.registry,
        )
        self.capture_fps = Gauge(
            "sentinel_vision_capture_fps",
            "Current camera capture rate",
            ("source",),
            registry=self.registry,
        )
        self.inference_fps = Gauge(
            "sentinel_vision_inference_fps",
            "Current inference rate",
            ("source",),
            registry=self.registry,
        )
        self.frames = Counter(
            "sentinel_vision_frames_total",
            "Monotonic frame counts reported by the vision worker",
            ("source", "stage"),
            registry=self.registry,
        )
        self.track_observations = Counter(
            "sentinel_track_observations_total",
            "Confirmed anonymous track observations",
            ("object_class",),
            registry=self.registry,
        )
        self.track_ids_created = Counter(
            "sentinel_track_ids_created_total",
            "New anonymous track IDs observed by the API",
            ("object_class",),
            registry=self.registry,
        )
        self.track_confidence = Histogram(
            "sentinel_track_confidence",
            "Raw detector confidence for confirmed tracks",
            ("object_class",),
            buckets=(0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.0),
            registry=self.registry,
        )
        self.events = Counter(
            "sentinel_events_total",
            "Security events emitted by type and severity",
            ("event_type", "severity", "origin"),
            registry=self.registry,
        )
        self.event_to_alert_latency = Histogram(
            "sentinel_event_to_alert_latency_seconds",
            "Event timestamp to operator broadcast latency",
            ("severity",),
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.llm_reviews = Counter(
            "sentinel_llm_reviews_total",
            "Advisory-only LLM outcomes",
            ("provider", "verdict"),
            registry=self.registry,
        )
        self.llm_latency = Histogram(
            "sentinel_llm_review_latency_seconds",
            "Evidence request to advisory review latency",
            ("provider",),
            buckets=(0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 60),
            registry=self.registry,
        )
        self.service_up = Gauge(
            "sentinel_service_up",
            "Dependency and worker availability (1 up, 0 down)",
            ("service",),
            registry=self.registry,
        )
        self.queue_depth = Gauge(
            "sentinel_queue_depth",
            "Current in-memory or durable queue depth",
            ("layer",),
            registry=self.registry,
        )
        self.outbox_oldest_age = Gauge(
            "sentinel_outbox_oldest_age_seconds",
            "Age of the oldest undelivered durable record",
            ("channel",),
            registry=self.registry,
        )
        self.dead_letters = Gauge(
            "sentinel_mqtt_dead_letters",
            "Critical records currently waiting on the MQTT dead-letter topic",
            registry=self.registry,
        )
        self.circuit_open = Gauge(
            "sentinel_circuit_open",
            "Circuit-breaker state (1 open/half-open, 0 closed)",
            ("component",),
            registry=self.registry,
        )
        self.uptime = Gauge(
            "sentinel_process_uptime_seconds",
            "API process uptime",
            registry=self.registry,
        )

    def record_http(
        self, method: str, route: str, status_code: int, duration_ms: float
    ) -> None:
        self.http_requests.labels(method, route, str(status_code)).inc()
        self.http_latency.labels(method, route).observe(max(duration_ms, 0) / 1000)

    def record_vision(self, sample: VisionMetrics) -> None:
        source = sample.source[:96]
        self.capture_fps.labels(source).set(sample.capture_fps)
        self.inference_fps.labels(source).set(sample.inference_fps)
        if sample.last_inference_ms is not None:
            self.inference_latency.labels(source).observe(sample.last_inference_ms)
        if sample.last_end_to_end_ms is not None:
            self.end_to_end_latency.labels(source).observe(sample.last_end_to_end_ms)
        current = {
            "captured": sample.frames_captured,
            "inferred": sample.frames_inferred,
            "posted": sample.frames_posted,
            "dropped": sample.frames_dropped_for_latency,
        }
        with self._lock:
            previous = self._vision_previous.get(source, {})
            for stage, value in current.items():
                prior = previous.get(stage, 0)
                delta = value - prior if value >= prior else value
                if delta > 0:
                    self.frames.labels(source, stage).inc(delta)
            self._vision_previous[source] = current
        self.service_up.labels(f"vision:{source}").set(
            1 if sample.status == "processing" else 0
        )

    def record_track(self, track: dict[str, Any]) -> None:
        object_class = str(track.get("class", "unknown"))[:64]
        track_id = str(track.get("track_id", ""))[:128]
        observed_at = float(track.get("timestamp", time.time()))
        self.track_observations.labels(object_class).inc()
        confidence = track.get("confidence")
        if isinstance(confidence, (int, float)):
            self.track_confidence.labels(object_class).observe(float(confidence))
        with self._lock:
            if track_id and track_id not in self._seen_tracks:
                self.track_ids_created.labels(object_class).inc()
            if track_id:
                self._seen_tracks[track_id] = observed_at
            cutoff = observed_at - 3600
            self._seen_tracks = {
                key: seen_at
                for key, seen_at in self._seen_tracks.items()
                if seen_at >= cutoff
            }

    def record_event(self, event: Event) -> None:
        self.events.labels(event.event_type, event.severity, event.origin[:64]).inc()
        self.event_to_alert_latency.labels(event.severity).observe(
            max(0.0, time.time() - event.timestamp)
        )

    def record_llm_review(
        self, verification: EvidenceVerification, requested_at: float
    ) -> None:
        provider = verification.provider[:64]
        self.llm_reviews.labels(provider, verification.verdict).inc()
        self.llm_latency.labels(provider).observe(
            max(0.0, verification.reviewed_at - requested_at)
        )

    def update_runtime(
        self,
        *,
        mqtt_connected: bool,
        postgis_available: bool,
        pipeline_health: dict[str, Any],
        llm_health: dict[str, Any],
    ) -> None:
        self.uptime.set(max(0.0, time.time() - self.started_at))
        self.service_up.labels("api").set(1)
        self.service_up.labels("mqtt").set(1 if mqtt_connected else 0)
        self.service_up.labels("postgis").set(1 if postgis_available else 0)
        self.service_up.labels("llm-advisory").set(
            1 if llm_health.get("enabled") and llm_health.get("worker") else 0
        )
        for layer, depth in pipeline_health.get("queues", {}).items():
            self.queue_depth.labels(str(layer)[:64]).set(float(depth))
        durable = pipeline_health.get("durable_queue", {})
        for channel in ("mqtt", "storage"):
            details = durable.get(channel, {})
            self.outbox_oldest_age.labels(channel).set(
                float(details.get("oldest_age_s", 0))
            )
        self.dead_letters.set(
            float(durable.get("mqtt", {}).get("dead_letters", 0))
        )
        for component, details in pipeline_health.get("circuits", {}).items():
            self.circuit_open.labels(str(component)[:64]).set(
                0 if details.get("state") == "closed" else 1
            )

    def render(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST
