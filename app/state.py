import asyncio
import time
from collections import deque
from fastapi import WebSocket
from .geofence import DEFAULT_GEOFENCE
from .schemas import (
    EvidenceRequest,
    EvidenceVerification,
    Event,
    Geofence,
    MissionRecord,
    RangeMeasurement,
    SecurityAdvisory,
    SecurityFinding,
    Telemetry,
    V2XDeviceStatus,
    V2XHeartbeat,
    VisionMetrics,
)


class OperationsState:
    def __init__(
        self,
        *,
        active_track_ttl_s: float = 8.0,
        track_occluded_after_s: float = 0.75,
        track_temporarily_lost_after_s: float = 2.0,
        track_reacquired_after_s: float = 0.75,
        v2x_device_offline_s: float = 15.0,
    ) -> None:
        self.active_track_ttl_s = max(active_track_ttl_s, 1.0)
        self.track_occluded_after_s = max(track_occluded_after_s, 0.1)
        self.track_temporarily_lost_after_s = min(
            max(track_temporarily_lost_after_s, self.track_occluded_after_s),
            self.active_track_ttl_s,
        )
        self.track_reacquired_after_s = max(track_reacquired_after_s, 0.1)
        self.v2x_device_offline_s = max(v2x_device_offline_s, 2.0)
        self.telemetry: Telemetry | None = None
        self.telemetry_history: deque[Telemetry] = deque(maxlen=1200)
        self.telemetry_by_vehicle: dict[str, Telemetry] = {}
        self.telemetry_history_by_vehicle: dict[str, deque[Telemetry]] = {}
        self.range_measurement: RangeMeasurement | None = None
        self.range_by_vehicle: dict[str, RangeMeasurement] = {}
        self.tracks: dict[str, dict] = {}
        self.track_persisted_at: dict[str, float] = {}
        self.faces: dict[str, dict] = {}
        self.vision_metrics: dict[str, VisionMetrics] = {}
        self.vision_preview: dict | None = None
        self.evidence_requests: list[EvidenceRequest] = []
        self.evidence_verifications: list[EvidenceVerification] = []
        self.security_findings: list[SecurityFinding] = []
        self.security_advisories: list[SecurityAdvisory] = []
        self.v2x_devices: dict[str, V2XDeviceStatus] = {}
        self.events: deque[Event] = deque(maxlen=5_000)
        self.missions: dict[str, MissionRecord] = {}
        self.geofences: list[Geofence] = [DEFAULT_GEOFENCE]
        self.clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    def record_telemetry(self, telemetry: Telemetry) -> None:
        self.telemetry = telemetry
        self.telemetry_history.append(telemetry)
        key = telemetry.vehicle_id or f"unidentified:{telemetry.source}"
        self.telemetry_by_vehicle[key] = telemetry
        history = self.telemetry_history_by_vehicle.setdefault(key, deque(maxlen=1200))
        history.append(telemetry)

    def record_range(self, measurement: RangeMeasurement) -> None:
        self.range_measurement = measurement
        key = measurement.vehicle_id or f"unidentified:{measurement.source}"
        self.range_by_vehicle[key] = measurement

    def record_track(self, track: dict) -> dict:
        """Record an anonymous observation and expose its short-term lifecycle."""
        payload = dict(track)
        track_id = str(payload["track_id"])
        observed_at = float(payload.get("timestamp", time.time()))
        previous = self.tracks.get(track_id)
        if previous is None:
            lifecycle = "NEW"
        else:
            gap_s = max(0.0, observed_at - float(previous.get("timestamp", 0)))
            lifecycle = (
                "REACQUIRED"
                if gap_s >= self.track_reacquired_after_s
                else "ACTIVE"
            )
        payload["lifecycle_state"] = lifecycle
        payload["last_seen_at"] = observed_at
        self.tracks[track_id] = payload
        return payload

    def track_snapshot(self, *, now: float | None = None) -> list[dict]:
        observed_at = time.time() if now is None else now
        output: list[dict] = []
        for track in self.tracks.values():
            payload = dict(track)
            age_s = max(0.0, observed_at - float(payload.get("timestamp", 0)))
            if age_s >= self.track_temporarily_lost_after_s:
                payload["lifecycle_state"] = "TEMPORARILY_LOST"
            elif age_s >= self.track_occluded_after_s:
                payload["lifecycle_state"] = "OCCLUDED"
            payload["age_s"] = round(age_s, 3)
            output.append(payload)
        return output

    def nearest_telemetry(
        self, timestamp: float, max_skew_s: float, vehicle_id: str | None = None
    ) -> Telemetry | None:
        history = (
            self.telemetry_history_by_vehicle.get(vehicle_id, deque())
            if vehicle_id
            else self.telemetry_history
        )
        if not history:
            return None
        candidate = min(
            history, key=lambda item: abs(item.timestamp - timestamp)
        )
        return candidate if abs(candidate.timestamp - timestamp) <= max_skew_s else None

    def nearest_range(
        self, timestamp: float, max_age_s: float, vehicle_id: str | None = None
    ) -> RangeMeasurement | None:
        candidate = (
            self.range_by_vehicle.get(vehicle_id)
            if vehicle_id
            else self.range_measurement
        )
        if candidate is None or abs(timestamp - candidate.timestamp) > max_age_s:
            return None
        return candidate

    def record_vision_metrics(self, metrics: VisionMetrics) -> list[str]:
        self.vision_metrics[metrics.source] = metrics
        return self.expire_tracks(metrics.timestamp, source=metrics.source)

    def expire_tracks(
        self, now: float | None = None, *, source: str | None = None
    ) -> list[str]:
        """Remove stale *live* tracks without removing their persisted history."""
        observed_at = time.time() if now is None else now
        expired = [
            track_id
            for track_id, track in self.tracks.items()
            if (source is None or track.get("source") == source)
            and observed_at - float(track.get("timestamp", 0)) > self.active_track_ttl_s
        ]
        for track_id in expired:
            self.tracks.pop(track_id, None)
            self.track_persisted_at.pop(track_id, None)
        return expired

    def record_vision_preview(
        self, source: str, timestamp: float, image: bytes
    ) -> None:
        # Keep one current preview only. It is not part of the core pipeline.
        self.vision_preview = {"source": source, "timestamp": timestamp, "image": image}

    def record_evidence_request(self, request: EvidenceRequest) -> None:
        self.evidence_requests.append(request)
        self.evidence_requests = self.evidence_requests[-100:]

    def record_evidence_verification(self, verification: EvidenceVerification) -> None:
        self.evidence_verifications.append(verification)
        self.evidence_verifications = self.evidence_verifications[-100:]

    def record_security_finding(self, finding: SecurityFinding) -> None:
        self.security_findings.append(finding)
        self.security_findings = self.security_findings[-200:]

    def record_security_advisory(self, advisory: SecurityAdvisory) -> None:
        self.security_advisories.append(advisory)
        self.security_advisories = self.security_advisories[-100:]

    def record_v2x_heartbeat(
        self, heartbeat: V2XHeartbeat, *, received_at: float | None = None
    ) -> V2XDeviceStatus | None:
        """Accept only a strictly increasing per-device sequence."""
        observed_at = time.time() if received_at is None else received_at
        previous = self.v2x_devices.get(heartbeat.device_id)
        if previous is not None and heartbeat.sequence <= previous.last_sequence:
            return None
        status = V2XDeviceStatus(
            device_id=heartbeat.device_id,
            device_type=heartbeat.device_type,
            link_status=heartbeat.reported_status,
            transport=heartbeat.transport,
            capabilities=heartbeat.capabilities,
            firmware_version=heartbeat.firmware_version,
            last_seen_at=observed_at,
            reported_at=heartbeat.sent_at,
            age_s=0,
            clock_skew_s=round(heartbeat.sent_at - observed_at, 3),
            last_sequence=heartbeat.sequence,
        )
        self.v2x_devices[heartbeat.device_id] = status
        return status

    def v2x_device_snapshot(self, *, now: float | None = None) -> list[dict]:
        observed_at = time.time() if now is None else now
        devices: list[dict] = []
        for status in self.v2x_devices.values():
            age_s = max(0.0, observed_at - status.last_seen_at)
            payload = status.model_dump()
            payload["age_s"] = round(age_s, 2)
            if age_s > self.v2x_device_offline_s:
                payload["link_status"] = "offline"
            devices.append(payload)
        return sorted(
            devices,
            key=lambda item: (item["link_status"] == "offline", item["device_id"]),
        )

    def snapshot(self) -> dict:
        self.expire_tracks()
        return {
            "telemetry": self.telemetry.model_dump() if self.telemetry else None,
            "telemetry_by_vehicle": {
                key: value.model_dump() for key, value in self.telemetry_by_vehicle.items()
            },
            "range_measurement": self.range_measurement.model_dump()
            if self.range_measurement
            else None,
            "tracks": self.track_snapshot(),
            "faces": list(self.faces.values()),
            "vision_metrics": [
                metrics.model_dump() for metrics in self.vision_metrics.values()
            ],
            "evidence_requests": [
                request.model_dump() for request in self.evidence_requests[-50:]
            ],
            "evidence_verifications": [
                verification.model_dump()
                for verification in self.evidence_verifications[-50:]
            ],
            "security_findings": [
                finding.model_dump() for finding in self.security_findings[-100:]
            ],
            "security_advisories": [
                advisory.model_dump() for advisory in self.security_advisories[-50:]
            ],
            "v2x_devices": self.v2x_device_snapshot(),
            "events": [event.model_dump() for event in list(self.events)[-50:]],
            "geofences": [geofence.model_dump() for geofence in self.geofences],
            "missions": [
                mission.model_dump(mode="json")
                for mission in sorted(
                    self.missions.values(),
                    key=lambda item: item.updated_at,
                    reverse=True,
                )[:100]
            ],
        }

    async def broadcast(self, message_type: str, data: dict) -> None:
        stale: list[WebSocket] = []
        for client in self.clients.copy():
            try:
                await client.send_json({"type": message_type, "data": data})
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)
