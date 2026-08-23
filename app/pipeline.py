"""Fault-isolated, asynchronous backend pipeline.

Ingress is intentionally fast. Perception never waits for database writes, and
storage/MQTT failures are isolated to their own workers with retry backoff.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal
from uuid import uuid4
from .behavior import BehaviorEngine
from .calibration import load_camera_extrinsics, load_intrinsic_calibration
from .config import Settings
from .durable_queue import DurableQueue, DurableQueueFull, DurableRecord
from .evidence import create_detection_advisory_request, create_evidence_request
from .events import EventEngine
from .geofence import contains
from .geolocation import estimate_location
from .mqtt import qos_for_topic
from .observability import (
    bind_correlation_id,
    bind_trace_context,
    reset_correlation_id,
    reset_trace_context,
)
from .resilience import CircuitBreaker
from .risk_engine import RiskEngine
from .schemas import Detection, DetectionBatch, EvidenceRequest, Event, EventProvenance
from .state import OperationsState
from .v2x import create_envelope

LOGGER = logging.getLogger(__name__)
StorageRecord = tuple[Literal["track", "event", "evidence"], dict | Event]


@dataclass
class ProcessedTrack:
    track: dict
    detection: Detection
    location: object | None
    inside_restricted: bool


class LayeredPipeline:
    def __init__(
        self,
        settings: Settings,
        state: OperationsState,
        event_engine: EventEngine,
        risk_engine: RiskEngine,
        on_track: Callable[[dict], Awaitable[None]],
        on_faces: Callable[[dict], Awaitable[None]],
        on_event: Callable[[Event], Awaitable[None]],
        on_evidence_request: Callable[[EvidenceRequest], Awaitable[None]],
        persist_track: Callable[[dict], None],
        persist_event: Callable[[Event], None],
        persist_evidence: Callable[[dict], None],
        publish: Callable[[str, dict, int | None], None],
        durable_queue: DurableQueue,
    ) -> None:
        self.settings, self.state = settings, state
        self.event_engine, self.risk_engine = event_engine, risk_engine
        self.camera_fx_px = settings.camera_fx_px
        self.camera_fy_px = settings.camera_fy_px
        self.camera_cx_px = settings.camera_cx_px
        self.camera_cy_px = settings.camera_cy_px
        self.camera_distortion: tuple[float, ...] = ()
        self.camera_rotation = settings.camera_to_body_rotation
        self.camera_calibration_version: str | None = None
        self.camera_calibration_sha256: str | None = None
        self.camera_calibration_image_size: tuple[int, int] | None = None
        self.camera_extrinsics_version: str | None = None
        self.camera_extrinsics_sha256: str | None = None
        if settings.camera_calibration_file:
            calibration = load_intrinsic_calibration(
                settings.camera_calibration_file, settings.camera_id
            )
            self.camera_fx_px = calibration.fx_px
            self.camera_fy_px = calibration.fy_px
            self.camera_cx_px = calibration.cx_px
            self.camera_cy_px = calibration.cy_px
            self.camera_distortion = calibration.distortion
            self.camera_calibration_version = calibration.version
            self.camera_calibration_sha256 = calibration.sha256
            self.camera_calibration_image_size = (
                calibration.image_width,
                calibration.image_height,
            )
        if settings.camera_extrinsics_file:
            extrinsics = load_camera_extrinsics(
                settings.camera_extrinsics_file, settings.camera_id
            )
            self.camera_rotation = extrinsics.rotation
            self.camera_extrinsics_version = extrinsics.version
            self.camera_extrinsics_sha256 = extrinsics.sha256
        self.behavior_engine = BehaviorEngine(
            loiter_window_s=settings.loiter_window_s,
            loiter_radius_m=settings.loiter_radius_m,
            proximity_distance_m=settings.proximity_warning_distance_m,
            event_cooldown_s=settings.behavior_event_cooldown_s,
            track_ttl_s=settings.behavior_track_ttl_s,
        )
        self.on_track, self.on_faces, self.on_event = on_track, on_faces, on_event
        self.on_evidence_request = on_evidence_request
        self.persist_track, self.persist_event, self.persist_evidence, self.publish = (
            persist_track,
            persist_event,
            persist_evidence,
            publish,
        )
        self.durable_queue = durable_queue
        size = settings.pipeline_queue_size
        self.ingress: asyncio.Queue[DetectionBatch] = asyncio.Queue(maxsize=size)
        self.rules: asyncio.Queue[ProcessedTrack] = asyncio.Queue(maxsize=size)
        self._storage_wakeup = asyncio.Event()
        self._egress_wakeup = asyncio.Event()
        self.tasks: list[asyncio.Task] = []
        self.dropped = 0
        self.duplicates = 0
        self.errors: dict[str, int] = {
            "fusion": 0,
            "rules": 0,
            "storage": 0,
            "egress": 0,
        }
        self.storage_circuit = CircuitBreaker(
            settings.delivery_circuit_failure_threshold,
            settings.delivery_circuit_cooldown_s,
        )
        self.egress_circuit = CircuitBreaker(
            settings.delivery_circuit_failure_threshold,
            settings.delivery_circuit_cooldown_s,
        )
        # Per-track rate limit.  It bounds cloud cost and ensures provider
        # latency never becomes part of the real-time perception loop.
        self._last_detection_advisory_at: dict[str, float] = {}

    async def start(self) -> None:
        self.tasks = [
            asyncio.create_task(self._fusion_worker(), name="fusion-layer"),
            asyncio.create_task(self._rules_worker(), name="rules-layer"),
            asyncio.create_task(self._storage_worker(), name="storage-layer"),
            asyncio.create_task(self._egress_worker(), name="egress-layer"),
        ]
        self._storage_wakeup.set()
        self._egress_wakeup.set()

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    @staticmethod
    def _batch_identity(batch: DetectionBatch) -> str:
        if batch.batch_id:
            return batch.batch_id
        material = (
            f"{batch.source}|{batch.captured_at or batch.timestamp:.6f}|"
            f"{batch.frame_width}x{batch.frame_height}|{batch.model_name or ''}"
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def submit(self, batch: DetectionBatch) -> Literal["accepted", "duplicate", "full"]:
        idempotency_key = f"detection:{self._batch_identity(batch)}"
        if not self.durable_queue.claim_idempotency(
            idempotency_key, self.settings.detection_idempotency_ttl_s
        ):
            self.duplicates += 1
            return "duplicate"
        try:
            self.ingress.put_nowait(batch)
            return "accepted"
        except asyncio.QueueFull:
            self.durable_queue.release_idempotency(idempotency_key)
            self.dropped += 1
            return "full"

    def claim_v2x_message(self, message_id: str) -> bool:
        return self.durable_queue.claim_idempotency(
            f"v2x:{message_id}", self.settings.v2x_idempotency_ttl_s
        )

    @staticmethod
    def _transport_coalesce_key(topic: str, payload: dict) -> str | None:
        if topic == "ground/tracks" and payload.get("track_id"):
            return f"mqtt:{topic}:{payload['track_id']}"
        if topic == "ground/vision/metrics":
            return f"mqtt:{topic}:{payload.get('source', 'unknown')}"
        if topic in {"drone/pose", "drone/range"}:
            return f"mqtt:{topic}"
        return None

    def queue_transport(self, topic: str, payload: dict) -> None:
        try:
            qos = qos_for_topic(self.settings, topic)
            priority = 100 if qos == 2 else 30
            self.durable_queue.enqueue(
                "mqtt",
                topic,
                payload,
                qos=qos,
                priority=priority,
                coalesce_key=self._transport_coalesce_key(topic, payload),
            )
            self._egress_wakeup.set()
        except DurableQueueFull:
            self.dropped += 1
            LOGGER.critical("Durable egress queue full for %s", topic)
            if qos == 2:
                raise

    def health(self) -> dict:
        durable = self.durable_queue.stats()
        return {
            "queues": {
                "ingress": self.ingress.qsize(),
                "rules": self.rules.qsize(),
                "storage": durable["storage"]["pending"],
                "egress": durable["mqtt"]["pending"],
            },
            "dropped": self.dropped,
            "duplicates": self.duplicates,
            "errors": self.errors,
            "workers": {task.get_name(): not task.done() for task in self.tasks},
            "durable_queue": durable,
            "circuits": {
                "storage": self.storage_circuit.health(),
                "egress": self.egress_circuit.health(),
            },
        }

    async def _fusion_worker(self) -> None:
        while True:
            batch = await self.ingress.get()
            batch_identity = self._batch_identity(batch)
            correlation_token = bind_correlation_id(batch_identity)
            trace_material = batch_identity.encode("utf-8")
            trace_tokens = bind_trace_context(
                hashlib.sha256(trace_material).hexdigest()[:32],
                hashlib.sha256(trace_material + b":pipeline").hexdigest()[:16],
            )
            try:
                await self._fuse_batch(batch)
            except Exception:
                self.errors["fusion"] += 1
                LOGGER.exception("Fusion layer rejected a detection batch")
            finally:
                reset_trace_context(trace_tokens)
                reset_correlation_id(correlation_token)
                self.ingress.task_done()

    async def _fuse_batch(self, batch: DetectionBatch) -> None:
        if batch.faces:
            await self.on_faces(
                {
                    "source": batch.source,
                    "timestamp": batch.timestamp,
                    "count": len(batch.faces),
                    "faces": [face.model_dump() for face in batch.faces],
                }
            )
        pose = self.state.nearest_telemetry(
            batch.timestamp, self.settings.telemetry_max_skew_s, batch.vehicle_id
        )
        fresh_range = self.state.nearest_range(
            batch.timestamp, self.settings.lidar_max_age_s, batch.vehicle_id
        )
        frame_fx = self.camera_fx_px
        frame_fy = self.camera_fy_px
        frame_cx = self.camera_cx_px
        frame_cy = self.camera_cy_px
        frame_calibration_version = self.camera_calibration_version
        frame_calibration_sha256 = self.camera_calibration_sha256
        if self.camera_calibration_image_size:
            calibration_width, calibration_height = self.camera_calibration_image_size
            source_aspect = calibration_width / calibration_height
            frame_aspect = batch.frame_width / batch.frame_height
            if abs(source_aspect - frame_aspect) / source_aspect > 0.01:
                frame_fx = frame_fy = frame_cx = frame_cy = 0
                frame_calibration_version = None
                frame_calibration_sha256 = None
            else:
                scale_x = batch.frame_width / calibration_width
                scale_y = batch.frame_height / calibration_height
                frame_fx *= scale_x
                frame_fy *= scale_y
                frame_cx *= scale_x
                frame_cy *= scale_y
        for detection in batch.detections:
            location = detection.location
            if location is None and pose:
                location = estimate_location(
                    detection.bbox.x + detection.bbox.width / 2,
                    detection.bbox.y + detection.bbox.height / 2,
                    batch.frame_width,
                    batch.frame_height,
                    pose,
                    self.settings.camera_fov_horizontal_deg,
                    self.settings.camera_fov_vertical_deg,
                    fresh_range,
                    frame_fx,
                    frame_fy,
                    frame_cx,
                    frame_cy,
                    self.settings.enable_ray_plane_geolocation,
                    self.camera_rotation,
                    batch.timestamp,
                    self.camera_distortion,
                )
            inside = (
                any(
                    contains(location, zone)
                    for zone in self.state.geofences
                    if zone.restricted
                )
                if location
                else False
            )
            assessment = self.risk_engine.assess(detection, inside, batch.timestamp)
            track = {
                "track_id": detection.track_id,
                "class": detection.class_name,
                "model_class": detection.model_class,
                "confidence": detection.confidence,
                "display_confidence": detection.display_confidence
                if detection.display_confidence is not None
                else detection.confidence,
                "bbox": detection.bbox.model_dump(),
                "motion": detection.motion.model_dump() if detection.motion else None,
                "confirmed_track_observations": detection.confirmed_track_observations,
                "track_mean_confidence": detection.track_mean_confidence,
                "track_class_stability": detection.track_class_stability,
                "person_verification": detection.person_verification.model_dump()
                if detection.person_verification
                else None,
                "fall": detection.fall.model_dump() if detection.fall else None,
                "evidence_ref": detection.evidence_ref,
                "evidence": detection.evidence.model_dump()
                if detection.evidence
                else None,
                "location": location.model_dump() if location else None,
                "risk": assessment.__dict__,
                "timestamp": batch.timestamp,
                "captured_at": batch.captured_at,
                "model_name": batch.model_name,
                "model_version": batch.model_version,
                "model_sha256": batch.model_sha256,
                "model_integrity_verified": batch.model_integrity_verified,
                "inference_ms": batch.inference_ms,
                "source": batch.source,
                "vehicle_id": batch.vehicle_id,
                "correlation_id": batch.batch_id,
                "camera_calibration_version": frame_calibration_version,
                "camera_calibration_sha256": frame_calibration_sha256,
                "camera_extrinsics_version": self.camera_extrinsics_version,
                "camera_extrinsics_sha256": self.camera_extrinsics_sha256,
            }
            await self.on_track(track)
            if track["evidence"]:
                self._queue_storage(("evidence", track))
            self.queue_transport("ground/tracks", track)
            if detection.fall and location:
                fall_score = max(assessment.score, 80 if inside else 60)
                fall_event = Event(
                    id=str(uuid4()),
                    timestamp=batch.timestamp,
                    event_type="fall_detected",
                    severity="critical" if inside else "warning",
                    rule_id="pose-fall-temporal",
                    rule_version="1",
                    track_id=detection.track_id,
                    geofence_id="restricted-area"
                    if inside
                    else "camera:fall-observation",
                    message=(
                        f"Possible fall observed for anonymous track {detection.track_id}; "
                        f"pose confidence {detection.fall.confidence:.0%}."
                    ),
                    location=location,
                    risk_score=fall_score,
                    risk_factors=assessment.factors
                    + ["behavior:fall_pose", "requires_operator_review"],
                )
                await self.dispatch_event(fall_event)
            await self._maybe_request_detection_advisory(track)
            last_saved = self.state.track_persisted_at.get(detection.track_id, 0)
            if batch.timestamp - last_saved >= 1:
                self.state.track_persisted_at[detection.track_id] = batch.timestamp
                self._queue_storage(("track", track))
            self._queue_rules(ProcessedTrack(track, detection, location, inside))

    async def _rules_worker(self) -> None:
        while True:
            item = await self.rules.get()
            try:
                if item.location:
                    assessment = self.risk_engine.assess(
                        item.detection, item.inside_restricted, item.track["timestamp"]
                    )
                    for geofence in self.state.geofences:
                        event = self.event_engine.observe(
                            item.detection.track_id,
                            item.location,
                            geofence,
                            contains(item.location, geofence),
                            item.track["timestamp"],
                        )
                        if event:
                            await self.dispatch_event(
                                self.risk_engine.apply(event, assessment)
                            )
                    if self.settings.enable_behavior_analytics:
                        for event in self.behavior_engine.observe(
                            item.detection.track_id,
                            item.detection.class_name,
                            item.location,
                            item.track["timestamp"],
                        ):
                            event = self.risk_engine.apply(event, assessment)
                            event.risk_factors.append(f"behavior:{event.event_type}")
                            await self.dispatch_event(event)
            except Exception:
                self.errors["rules"] += 1
                LOGGER.exception("Rules layer failed for a track")
            finally:
                self.rules.task_done()

    async def _storage_worker(self) -> None:
        while True:
            if not self.storage_circuit.allow_request():
                await asyncio.sleep(0.25)
                continue
            record = await asyncio.to_thread(self.durable_queue.next_due, "storage")
            if record is None:
                self._storage_wakeup.clear()
                try:
                    await asyncio.wait_for(self._storage_wakeup.wait(), timeout=0.5)
                except TimeoutError:
                    self._storage_wakeup.clear()
                continue
            try:
                if record.destination == "track":
                    await asyncio.to_thread(self.persist_track, record.payload)
                elif record.destination == "evidence":
                    await asyncio.to_thread(self.persist_evidence, record.payload)
                else:
                    await asyncio.to_thread(self.persist_event, Event(**record.payload))
                await asyncio.to_thread(self.durable_queue.acknowledge, record.id)
                self.storage_circuit.record_success()
            except Exception as exc:
                self.errors["storage"] += 1
                self.storage_circuit.record_failure()
                delay = self._retry_delay(record)
                await asyncio.to_thread(
                    self.durable_queue.retry, record.id, type(exc).__name__, delay
                )
                LOGGER.warning(
                    "Storage delivery deferred",
                    extra={
                        "event": "storage_retry",
                        "component": "storage",
                        "record_id": record.id,
                        "attempt": record.attempts + 1,
                        "retry_delay_s": round(delay, 3),
                    },
                )

    async def _egress_worker(self) -> None:
        while True:
            if not self.egress_circuit.allow_request():
                await asyncio.sleep(0.25)
                continue
            record = await asyncio.to_thread(self.durable_queue.next_due, "mqtt")
            if record is None:
                self._egress_wakeup.clear()
                try:
                    await asyncio.wait_for(self._egress_wakeup.wait(), timeout=0.5)
                except TimeoutError:
                    self._egress_wakeup.clear()
                continue
            try:
                await asyncio.to_thread(
                    self.publish, record.destination, record.payload, record.qos
                )
                await asyncio.to_thread(self.durable_queue.acknowledge, record.id)
                self.egress_circuit.record_success()
            except Exception as exc:
                self.errors["egress"] += 1
                self.egress_circuit.record_failure()
                attempts = record.attempts + 1
                is_critical = record.qos == 2
                if (
                    is_critical
                    and attempts >= max(self.settings.delivery_max_attempts, 1)
                    and record.destination != self.settings.mqtt_dead_letter_topic
                ):
                    await asyncio.to_thread(
                        self.durable_queue.dead_letter,
                        record,
                        dead_letter_topic=self.settings.mqtt_dead_letter_topic,
                        error=type(exc).__name__,
                    )
                    LOGGER.error(
                        "Critical MQTT record moved to dead letter",
                        extra={
                            "event": "mqtt_dead_lettered",
                            "component": "mqtt",
                            "record_id": record.id,
                            "topic": record.destination,
                            "attempts": attempts,
                        },
                    )
                else:
                    delay = self._retry_delay(record)
                    await asyncio.to_thread(
                        self.durable_queue.retry,
                        record.id,
                        type(exc).__name__,
                        delay,
                    )
                    LOGGER.warning(
                        "MQTT delivery deferred",
                        extra={
                            "event": "mqtt_retry",
                            "component": "mqtt",
                            "record_id": record.id,
                            "topic": record.destination,
                            "attempt": attempts,
                            "retry_delay_s": round(delay, 3),
                        },
                    )

    def _retry_delay(self, record: DurableRecord) -> float:
        exponential = self.settings.delivery_retry_base_s * (
            2 ** min(record.attempts, 10)
        )
        bounded = min(exponential, self.settings.delivery_retry_max_s)
        # Stable per-record jitter prevents a reconnect stampede without using
        # a security-sensitive random source.
        jitter_byte = hashlib.sha256(
            f"{record.id}:{record.attempts}".encode("utf-8")
        ).digest()[0]
        return max(0.05, bounded * (0.85 + (jitter_byte / 255) * 0.3))

    def _queue_rules(self, item: ProcessedTrack) -> None:
        try:
            self.rules.put_nowait(item)
        except asyncio.QueueFull:
            self.dropped += 1
            LOGGER.warning("Rules queue full; dropped %s", item.track["track_id"])

    def _queue_storage(self, item: StorageRecord) -> None:
        kind, payload = item
        serialised = payload.model_dump(mode="json") if isinstance(payload, Event) else payload
        coalesce_key = (
            f"storage:track:{serialised.get('track_id')}" if kind == "track" else None
        )
        try:
            self.durable_queue.enqueue(
                "storage",
                kind,
                serialised,
                qos=0,
                priority=100 if kind == "event" else (80 if kind == "evidence" else 40),
                coalesce_key=coalesce_key,
            )
            self._storage_wakeup.set()
        except DurableQueueFull:
            self.dropped += 1
            LOGGER.critical("Durable storage queue full for %s", kind)
            if kind == "event":
                raise

    async def _maybe_request_detection_advisory(self, track: dict) -> None:
        """Submit at most one independent reviewer request per track window."""
        now = float(track["timestamp"])
        track_id = str(track["track_id"])
        cooldown = max(self.settings.llm_advisory_track_cooldown_s, 1.0)
        previous = self._last_detection_advisory_at.get(track_id)
        if previous is not None and now - previous < cooldown:
            return
        request = create_detection_advisory_request(self.settings, track)
        if request is None:
            return
        self._last_detection_advisory_at[track_id] = now
        # Expire bookkeeping independently from historical storage.
        self._last_detection_advisory_at = {
            key: seen_at
            for key, seen_at in self._last_detection_advisory_at.items()
            if now - seen_at <= cooldown * 2
        }
        await self.on_evidence_request(request)
        self.queue_transport(
            self.settings.evidence_requests_topic, request.model_dump(mode="json")
        )

    async def dispatch_event(self, event: Event, relay_v2x: bool = True) -> None:
        """Fan out after state/UI handling; persistence and transport remain isolated."""
        if event.origin == "local":
            track = self.state.tracks.get(event.track_id) or {}
            zone = next(
                (item for item in self.state.geofences if item.id == event.geofence_id),
                None,
            )
            evidence = track.get("evidence") or {}
            event = event.model_copy(
                update={
                    "vehicle_id": track.get("vehicle_id"),
                    "camera_id": track.get("source"),
                    "confidence": track.get("confidence"),
                    "correlation_id": track.get("correlation_id"),
                    "uncertainty_m": (track.get("location") or {}).get(
                        "uncertainty_m"
                    ),
                    "provenance": EventProvenance(
                        source_id=track.get("source"),
                        source_frame_timestamp=track.get("timestamp"),
                        captured_at=track.get("captured_at"),
                        detector_model=track.get("model_name"),
                        detector_version=track.get("model_version"),
                        detector_weights_sha256=track.get("model_sha256"),
                        detector_integrity_verified=bool(
                            track.get("model_integrity_verified", False)
                        ),
                        detector_confidence=track.get("confidence"),
                        geofence_version=zone.version if zone else None,
                        camera_calibration_version=track.get(
                            "camera_calibration_version"
                        ),
                        camera_calibration_sha256=track.get(
                            "camera_calibration_sha256"
                        ),
                        camera_extrinsics_version=track.get(
                            "camera_extrinsics_version"
                        ),
                        camera_extrinsics_sha256=track.get(
                            "camera_extrinsics_sha256"
                        ),
                        evidence_id=evidence.get("evidence_id"),
                        evidence_sha256=evidence.get("sha256"),
                    )
                }
            )
        window = max(self.settings.event_idempotency_window_s, 1.0)
        bucket = int(event.timestamp // window)
        fingerprint = (
            f"event:{event.origin}:{event.track_id}:{event.event_type}:"
            f"{event.geofence_id}:{bucket}"
        )
        if not self.durable_queue.claim_idempotency(fingerprint, window * 2):
            self.duplicates += 1
            return
        await self.on_event(event)
        payload = event.model_dump(mode="json")
        self._queue_storage(("event", event))
        self.queue_transport("ground/events", payload)
        if relay_v2x and self.settings.enable_v2x and self.settings.v2x_shared_secret:
            self.queue_transport(
                self.settings.v2x_events_topic,
                create_envelope(
                    event,
                    self.settings.v2x_source_id,
                    self.settings.v2x_shared_secret,
                    self.state.tracks.get(event.track_id),
                    self.state.telemetry,
                ),
            )
        request = create_evidence_request(
            self.settings,
            event,
            self.state.tracks.get(event.track_id),
            self.state.telemetry,
        )
        if request:
            await self.on_evidence_request(request)
            self.queue_transport(
                self.settings.evidence_requests_topic, request.model_dump(mode="json")
            )
