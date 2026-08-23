import logging
import json
import hashlib
import time
from typing import Any

from psycopg import Connection
from psycopg_pool import ConnectionPool

from .db_migrations import apply_migrations
from .schemas import Event, MissionRecord, SecurityFinding

LOGGER = logging.getLogger(__name__)


class Persistence:
    def __init__(
        self,
        database_url: str,
        *,
        write_pool_size: int = 4,
        read_pool_size: int = 4,
    ) -> None:
        self.database_url = database_url
        self.write_pool_size = max(write_pool_size, 1)
        self.read_pool_size = max(read_pool_size, 1)
        self.write_pool: ConnectionPool | None = None
        self.read_pool: ConnectionPool | None = None
        self.available = False

    def _ensure_pools(self) -> None:
        if self.write_pool is None or self.write_pool.closed:
            self.write_pool = ConnectionPool(
                self.database_url,
                min_size=1,
                max_size=self.write_pool_size,
                open=False,
                name="sentinel-ingestion-writes",
                timeout=3,
                reconnect_timeout=30,
            )
            self.write_pool.open(wait=True, timeout=3)
        if self.read_pool is None or self.read_pool.closed:
            self.read_pool = ConnectionPool(
                self.database_url,
                min_size=1,
                max_size=self.read_pool_size,
                open=False,
                name="sentinel-dashboard-reads",
                timeout=3,
                reconnect_timeout=30,
            )
            self.read_pool.open(wait=True, timeout=3)

    def connect(self) -> None:
        try:
            self._ensure_pools()
            assert self.write_pool is not None
            with self.write_pool.connection() as connection:
                connection.execute("SELECT 1")
                connection.execute("""CREATE TABLE IF NOT EXISTS events (
                    id UUID PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL,
                    event_type TEXT NOT NULL, severity TEXT NOT NULL,
                    track_id TEXT NOT NULL, geofence_id TEXT NOT NULL,
                    message TEXT NOT NULL, location geometry(Point, 4326) NOT NULL
                )""")
                connection.execute(
                    "ALTER TABLE events ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                connection.execute(
                    "ALTER TABLE events ADD COLUMN IF NOT EXISTS acknowledged BOOLEAN NOT NULL DEFAULT FALSE"
                )
                connection.execute(
                    "ALTER TABLE events ADD COLUMN IF NOT EXISTS reviewed_by TEXT"
                )
                connection.execute(
                    "ALTER TABLE events ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS events_occurred_idx ON events (occurred_at DESC)"
                )
                connection.execute(
                    """CREATE INDEX IF NOT EXISTS events_severity_occurred_idx
                    ON events (severity, occurred_at DESC)"""
                )
                connection.execute(
                    """CREATE INDEX IF NOT EXISTS events_track_occurred_idx
                    ON events (track_id, occurred_at DESC)"""
                )
                connection.execute("""CREATE TABLE IF NOT EXISTS tracks (
                    track_id TEXT NOT NULL, observed_at TIMESTAMPTZ NOT NULL, object_class TEXT NOT NULL,
                    confidence DOUBLE PRECISION NOT NULL, source TEXT NOT NULL, risk_score INTEGER NOT NULL,
                    bbox JSONB NOT NULL, location geometry(Point, 4326),
                    PRIMARY KEY (track_id, observed_at))""")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS tracks_location_idx ON tracks USING GIST (location)"
                )
                connection.execute(
                    """CREATE INDEX IF NOT EXISTS tracks_source_observed_idx
                    ON tracks (source, observed_at DESC)"""
                )
                connection.execute(
                    """CREATE INDEX IF NOT EXISTS tracks_class_observed_idx
                    ON tracks (object_class, observed_at DESC)"""
                )
                connection.execute("""CREATE TABLE IF NOT EXISTS security_findings (
                    id UUID PRIMARY KEY, observed_at TIMESTAMPTZ NOT NULL, source_id TEXT NOT NULL,
                    category TEXT NOT NULL, code TEXT NOT NULL, severity TEXT NOT NULL,
                    message TEXT NOT NULL, evidence JSONB NOT NULL, recommended_action TEXT NOT NULL
                )""")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS security_findings_observed_idx ON security_findings (observed_at DESC)"
                )
                connection.execute("""CREATE TABLE IF NOT EXISTS evidence_records (
                    evidence_id UUID PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL,
                    track_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    artifact_path TEXT NOT NULL UNIQUE,
                    artifact_sha256 CHAR(64) NOT NULL,
                    artifact_size_bytes BIGINT NOT NULL CHECK (artifact_size_bytes > 0),
                    manifest_path TEXT NOT NULL,
                    manifest_hmac_sha256 CHAR(64) NOT NULL,
                    encryption_format TEXT NOT NULL,
                    model_release TEXT,
                    model_weights_sha256 CHAR(64),
                    source_frame_timestamp TIMESTAMPTZ NOT NULL,
                    retention_until TIMESTAMPTZ NOT NULL,
                    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
                    legal_hold_reason TEXT,
                    legal_hold_by TEXT,
                    legal_hold_at TIMESTAMPTZ,
                    purged_at TIMESTAMPTZ
                )""")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS evidence_retention_idx ON evidence_records (retention_until) WHERE purged_at IS NULL AND legal_hold = FALSE"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS evidence_track_created_idx ON evidence_records (track_id, created_at DESC)"
                )
                self._create_audit_schema(connection)
                apply_migrations(connection)
                connection.commit()
            self.available = True
        except Exception as exc:
            self.available = False
            LOGGER.warning("PostGIS unavailable: %s", exc)

    def close(self) -> None:
        if self.write_pool is not None and not self.write_pool.closed:
            self.write_pool.close()
        if self.read_pool is not None and not self.read_pool.closed:
            self.read_pool.close()
        self.available = False

    @staticmethod
    def _create_audit_schema(connection: Connection[Any]) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            sequence BIGSERIAL PRIMARY KEY,
            occurred_at TIMESTAMPTZ NOT NULL,
            entry_data JSONB NOT NULL,
            previous_hash CHAR(64) NOT NULL,
            entry_hash CHAR(64) NOT NULL UNIQUE
        )""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS audit_log_occurred_idx ON audit_log (occurred_at DESC)"
        )
        connection.execute("""CREATE OR REPLACE FUNCTION sentinel_reject_audit_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'audit_log is append-only';
            END $$""")
        connection.execute("""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_log_append_only') THEN
                CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
                FOR EACH ROW EXECUTE FUNCTION sentinel_reject_audit_mutation();
            END IF;
        END $$""")

    @staticmethod
    def _audit_hash(previous_hash: str, entry_data: dict[str, Any]) -> str:
        canonical = json.dumps(
            entry_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(
            f"{previous_hash}\n{canonical}".encode("utf-8")
        ).hexdigest()

    def append_audit(
        self,
        *,
        actor: str,
        roles: list[str],
        action: str,
        target: str,
        justification: str,
        correlation_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable; auditable action rejected")
        entry_data = {
            "occurred_at_epoch": round(time.time(), 6),
            "actor": actor,
            "roles": sorted(set(roles)),
            "action": action,
            "target": target,
            "justification": justification[:500],
            "correlation_id": correlation_id,
            "metadata": metadata or {},
        }
        try:
            assert self.write_pool is not None
            with self.write_pool.connection() as connection:
                connection.execute("SELECT pg_advisory_xact_lock(731954120)")
                row = connection.execute(
                    "SELECT entry_hash FROM audit_log ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                previous_hash = row[0].strip() if row else "0" * 64
                entry_hash = self._audit_hash(previous_hash, entry_data)
                inserted = connection.execute(
                    """INSERT INTO audit_log (occurred_at, entry_data, previous_hash, entry_hash)
                    VALUES (to_timestamp(%s), %s::jsonb, %s, %s) RETURNING sequence""",
                    (
                        entry_data["occurred_at_epoch"],
                        json.dumps(entry_data),
                        previous_hash,
                        entry_hash,
                    ),
                ).fetchone()
                connection.commit()
            if inserted is None:
                raise RuntimeError("Audit insert returned no sequence")
            return {
                "sequence": inserted[0],
                "previous_hash": previous_hash,
                "entry_hash": entry_hash,
                **entry_data,
            }
        except Exception:
            self.available = False
            raise

    def verify_audit_chain(self) -> dict[str, Any]:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.read_pool is not None
        with self.read_pool.connection() as connection:
            rows = connection.execute(
                "SELECT sequence, entry_data, previous_hash, entry_hash FROM audit_log ORDER BY sequence"
            ).fetchall()
        expected_previous = "0" * 64
        for sequence, entry_data, previous_hash, entry_hash in rows:
            previous_hash, entry_hash = previous_hash.strip(), entry_hash.strip()
            expected_hash = self._audit_hash(expected_previous, entry_data)
            if previous_hash != expected_previous or entry_hash != expected_hash:
                return {
                    "valid": False,
                    "entries": len(rows),
                    "first_invalid_sequence": sequence,
                }
            expected_previous = entry_hash
        return {"valid": True, "entries": len(rows), "head_hash": expected_previous}

    def save_track(self, track: dict[str, Any]) -> None:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        location = track.get("location")
        try:
            assert self.write_pool is not None
            with self.write_pool.connection() as connection:
                connection.execute(
                    """INSERT INTO tracks (track_id, observed_at, object_class, confidence, source, risk_score, bbox, location)
                    VALUES (%s, to_timestamp(%s), %s, %s, %s, %s, %s::jsonb,
                    CASE WHEN %s THEN NULL ELSE ST_SetSRID(ST_MakePoint(%s, %s), 4326) END)
                    ON CONFLICT (track_id, observed_at) DO UPDATE SET confidence = EXCLUDED.confidence,
                    risk_score = EXCLUDED.risk_score, bbox = EXCLUDED.bbox, location = EXCLUDED.location""",
                    (
                        track["track_id"],
                        track["timestamp"],
                        track["class"],
                        track["confidence"],
                        track["source"],
                        track["risk"]["score"],
                        json.dumps(track["bbox"]),
                        location is None,
                        location["longitude"] if location else None,
                        location["latitude"] if location else None,
                    ),
                )
                connection.commit()
        except Exception:
            self.available = False
            raise

    def save_event(self, event: Event) -> None:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        try:
            assert self.write_pool is not None
            with self.write_pool.connection() as connection:
                connection.execute(
                    """INSERT INTO events
                    (id, occurred_at, event_type, severity, track_id, geofence_id,
                     message, location, provenance, acknowledged, state, vehicle_id,
                     camera_id, confidence, rule_id, rule_version, uncertainty_m,
                     correlation_id)
                    VALUES (%s, to_timestamp(%s), %s, %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s::jsonb, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                    acknowledged = EXCLUDED.acknowledged,
                    state = EXCLUDED.state,
                    provenance = EXCLUDED.provenance""",
                    (
                        event.id,
                        event.timestamp,
                        event.event_type,
                        event.severity,
                        event.track_id,
                        event.geofence_id,
                        event.message,
                        event.location.longitude,
                        event.location.latitude,
                        json.dumps(event.provenance.model_dump(mode="json")),
                        event.acknowledged,
                        event.state,
                        event.vehicle_id,
                        event.camera_id,
                        event.confidence,
                        event.rule_id,
                        event.rule_version,
                        event.uncertainty_m,
                        event.correlation_id,
                    ),
                )
                connection.commit()
        except Exception:
            self.available = False
            raise

    def query_history(
        self, start_timestamp: float, end_timestamp: float, limit: int
    ) -> list[dict[str, Any]]:
        """Return a bounded, read-only event/track timeline for explicit replay."""
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        try:
            assert self.read_pool is not None
            with self.read_pool.connection() as connection:
                event_rows = connection.execute(
                    """SELECT id::text, EXTRACT(EPOCH FROM occurred_at), event_type,
                              severity, track_id, message, state, confidence,
                              CASE WHEN location IS NULL THEN NULL ELSE ST_Y(location) END,
                              CASE WHEN location IS NULL THEN NULL ELSE ST_X(location) END,
                              correlation_id
                       FROM events
                       WHERE occurred_at >= to_timestamp(%s)
                         AND occurred_at <= to_timestamp(%s)
                       ORDER BY occurred_at DESC
                       LIMIT %s""",
                    (start_timestamp, end_timestamp, limit),
                ).fetchall()
                track_rows = connection.execute(
                    """SELECT track_id, EXTRACT(EPOCH FROM observed_at), object_class,
                              confidence, source, risk_score, bbox,
                              CASE WHEN location IS NULL THEN NULL ELSE ST_Y(location) END,
                              CASE WHEN location IS NULL THEN NULL ELSE ST_X(location) END
                       FROM tracks
                       WHERE observed_at >= to_timestamp(%s)
                         AND observed_at <= to_timestamp(%s)
                       ORDER BY observed_at DESC
                       LIMIT %s""",
                    (start_timestamp, end_timestamp, limit),
                ).fetchall()
            records = [
                {
                    "kind": "event",
                    "id": row[0],
                    "timestamp": float(row[1]),
                    "event_type": row[2],
                    "severity": row[3],
                    "track_id": row[4],
                    "message": row[5],
                    "state": row[6],
                    "confidence": row[7],
                    "location": (
                        {"latitude": row[8], "longitude": row[9]}
                        if row[8] is not None and row[9] is not None
                        else None
                    ),
                    "correlation_id": row[10],
                }
                for row in event_rows
            ]
            records.extend(
                {
                    "kind": "track",
                    "track_id": row[0],
                    "timestamp": float(row[1]),
                    "class": row[2],
                    "confidence": row[3],
                    "source": row[4],
                    "risk_score": row[5],
                    "bbox": row[6],
                    "location": (
                        {"latitude": row[7], "longitude": row[8]}
                        if row[7] is not None and row[8] is not None
                        else None
                    ),
                }
                for row in track_rows
            )
            return sorted(
                records,
                key=lambda item: float(item["timestamp"]),
                reverse=True,
            )[:limit]
        except Exception:
            self.available = False
            raise

    def save_evidence(self, track: dict[str, Any], retention_days: int) -> None:
        evidence = track.get("evidence")
        if not isinstance(evidence, dict):
            return
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        try:
            assert self.write_pool is not None
            with self.write_pool.connection() as connection:
                connection.execute(
                    """INSERT INTO evidence_records
                    (evidence_id, created_at, track_id, source_id, artifact_path,
                     artifact_sha256, artifact_size_bytes, manifest_path,
                     manifest_hmac_sha256, encryption_format, model_release,
                     model_weights_sha256, source_frame_timestamp, retention_until)
                    VALUES (%s, to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, to_timestamp(%s), to_timestamp(%s) + (%s * interval '1 day'))
                    ON CONFLICT (evidence_id) DO NOTHING""",
                    (
                        evidence["evidence_id"],
                        evidence["created_at"],
                        track["track_id"],
                        track["source"],
                        evidence["path"],
                        evidence["sha256"],
                        evidence["size_bytes"],
                        evidence["manifest_path"],
                        evidence["manifest_hmac_sha256"],
                        evidence["encryption_format"],
                        f"{track.get('model_name') or 'unknown'}:{track.get('model_version') or 'unknown'}",
                        track.get("model_sha256"),
                        track.get("captured_at") or track["timestamp"],
                        evidence["created_at"],
                        max(retention_days, 1),
                    ),
                )
                connection.commit()
        except Exception:
            self.available = False
            raise

    def review_event(
        self, event_id: str, *, acknowledged: bool, reviewer: str, reviewed_at: float
    ) -> None:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.write_pool is not None
        with self.write_pool.connection() as connection:
            result = connection.execute(
                """UPDATE events SET acknowledged = %s, reviewed_by = %s,
                reviewed_at = to_timestamp(%s),
                provenance = provenance || %s::jsonb WHERE id = %s""",
                (
                    acknowledged,
                    reviewer,
                    reviewed_at,
                    json.dumps(
                        {
                            "operator_reviewed": acknowledged,
                            "reviewed_by": reviewer,
                            "reviewed_at": reviewed_at,
                        }
                    ),
                    event_id,
                ),
            )
            if result.rowcount != 1:
                raise KeyError(event_id)
            connection.commit()

    def transition_event(
        self,
        event_id: str,
        *,
        state: str,
        reviewer: str,
        reviewed_at: float,
    ) -> None:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.write_pool is not None
        with self.write_pool.connection() as connection:
            result = connection.execute(
                """UPDATE events SET state = %s,
                acknowledged = CASE WHEN %s = 'ACKNOWLEDGED' THEN TRUE ELSE acknowledged END,
                reviewed_by = %s, reviewed_at = to_timestamp(%s),
                provenance = provenance || %s::jsonb WHERE id = %s""",
                (
                    state,
                    state,
                    reviewer,
                    reviewed_at,
                    json.dumps(
                        {
                            "operator_reviewed": True,
                            "reviewed_by": reviewer,
                            "reviewed_at": reviewed_at,
                        }
                    ),
                    event_id,
                ),
            )
            if result.rowcount != 1:
                raise KeyError(event_id)
            connection.commit()

    def save_mission(self, mission: MissionRecord) -> None:
        """Persist one optimistically versioned mission and its spatial route."""
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        payload = mission.model_dump(mode="json")
        assert self.write_pool is not None
        with self.write_pool.connection() as connection:
            if mission.version == 1:
                result = connection.execute(
                    """INSERT INTO missions
                    (id, name, vehicle_id, version, state, document, created_at,
                     updated_at, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, to_timestamp(%s),
                            to_timestamp(%s), %s)
                    ON CONFLICT (id) DO NOTHING""",
                    (
                        mission.id,
                        mission.name,
                        mission.vehicle_id,
                        mission.version,
                        mission.state,
                        json.dumps(payload),
                        mission.created_at,
                        mission.updated_at,
                        mission.updated_by,
                    ),
                )
            else:
                result = connection.execute(
                    """UPDATE missions SET name = %s, vehicle_id = %s,
                    version = %s, state = %s, document = %s::jsonb,
                    updated_at = to_timestamp(%s), updated_by = %s
                    WHERE id = %s AND version = %s""",
                    (
                        mission.name,
                        mission.vehicle_id,
                        mission.version,
                        mission.state,
                        json.dumps(payload),
                        mission.updated_at,
                        mission.updated_by,
                        mission.id,
                        mission.version - 1,
                    ),
                )
            if result.rowcount != 1:
                raise RuntimeError("Mission version conflict")
            connection.execute(
                "DELETE FROM mission_waypoints WHERE mission_id = %s", (mission.id,)
            )
            for waypoint in sorted(mission.waypoints, key=lambda item: item.sequence):
                connection.execute(
                    """INSERT INTO mission_waypoints
                    (mission_id, waypoint_id, sequence, command, altitude_m,
                     speed_mps, hold_time_s, location)
                    VALUES (%s, %s, %s, %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326))""",
                    (
                        mission.id,
                        waypoint.id,
                        waypoint.sequence,
                        waypoint.command,
                        waypoint.altitude_m,
                        waypoint.speed_mps,
                        waypoint.hold_time_s,
                        waypoint.longitude,
                        waypoint.latitude,
                    ),
                )
            connection.execute(
                """UPDATE missions SET route = (
                SELECT CASE WHEN COUNT(*) >= 2
                    THEN ST_MakeLine(location ORDER BY sequence) ELSE NULL END
                FROM mission_waypoints WHERE mission_id = %s
                ) WHERE id = %s""",
                (mission.id, mission.id),
            )
            connection.commit()

    def get_mission(self, mission_id: str) -> MissionRecord:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.read_pool is not None
        with self.read_pool.connection() as connection:
            row = connection.execute(
                "SELECT document FROM missions WHERE id = %s", (mission_id,)
            ).fetchone()
        if row is None:
            raise KeyError(mission_id)
        return MissionRecord.model_validate(row[0])

    def list_missions(self, limit: int = 100) -> list[MissionRecord]:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.read_pool is not None
        with self.read_pool.connection() as connection:
            rows = connection.execute(
                "SELECT document FROM missions ORDER BY updated_at DESC LIMIT %s",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [MissionRecord.model_validate(row[0]) for row in rows]

    def delete_mission(self, mission_id: str, expected_version: int) -> None:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.write_pool is not None
        with self.write_pool.connection() as connection:
            result = connection.execute(
                "DELETE FROM missions WHERE id = %s AND version = %s",
                (mission_id, expected_version),
            )
            if result.rowcount != 1:
                raise RuntimeError("Mission version conflict or mission not found")
            connection.commit()

    def set_evidence_legal_hold(
        self,
        evidence_id: str,
        *,
        legal_hold: bool,
        actor: str,
        justification: str,
    ) -> dict[str, Any]:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.write_pool is not None
        with self.write_pool.connection() as connection:
            row = connection.execute(
                """UPDATE evidence_records SET legal_hold = %s,
                legal_hold_reason = %s, legal_hold_by = %s,
                legal_hold_at = CURRENT_TIMESTAMP
                WHERE evidence_id = %s AND purged_at IS NULL
                RETURNING evidence_id::text, legal_hold, legal_hold_by,
                          EXTRACT(EPOCH FROM legal_hold_at)""",
                (legal_hold, justification, actor, evidence_id),
            ).fetchone()
            if row is None:
                raise KeyError(evidence_id)
            connection.commit()
        return {
            "evidence_id": row[0],
            "legal_hold": row[1],
            "legal_hold_by": row[2],
            "legal_hold_at": float(row[3]),
        }

    def due_evidence(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.read_pool is not None
        with self.read_pool.connection() as connection:
            rows = connection.execute(
                """SELECT evidence_id::text, artifact_path, manifest_path
                FROM evidence_records
                WHERE retention_until <= CURRENT_TIMESTAMP
                  AND legal_hold = FALSE AND purged_at IS NULL
                ORDER BY retention_until LIMIT %s""",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [
            {"evidence_id": row[0], "artifact_path": row[1], "manifest_path": row[2]}
            for row in rows
        ]

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.read_pool is not None
        with self.read_pool.connection() as connection:
            row = connection.execute(
                """SELECT evidence_id::text, artifact_path, artifact_sha256,
                artifact_size_bytes, manifest_path, manifest_hmac_sha256,
                legal_hold, purged_at IS NOT NULL
                FROM evidence_records WHERE evidence_id = %s""",
                (evidence_id,),
            ).fetchone()
        if row is None:
            raise KeyError(evidence_id)
        return {
            "evidence_id": row[0],
            "artifact_path": row[1],
            "artifact_sha256": row[2].strip(),
            "artifact_size_bytes": row[3],
            "manifest_path": row[4],
            "manifest_hmac_sha256": row[5].strip(),
            "legal_hold": row[6],
            "purged": row[7],
        }

    def mark_evidence_purged(self, evidence_id: str) -> None:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        assert self.write_pool is not None
        with self.write_pool.connection() as connection:
            connection.execute(
                """UPDATE evidence_records SET purged_at = CURRENT_TIMESTAMP
                WHERE evidence_id = %s AND legal_hold = FALSE AND purged_at IS NULL""",
                (evidence_id,),
            )
            connection.commit()

    def save_security_finding(self, finding: SecurityFinding) -> None:
        if not self.available:
            self.connect()
        if not self.available:
            raise ConnectionError("PostGIS is unavailable")
        try:
            assert self.write_pool is not None
            with self.write_pool.connection() as connection:
                connection.execute(
                    """INSERT INTO security_findings
                    (id, observed_at, source_id, category, code, severity, message, evidence, recommended_action)
                    VALUES (%s, to_timestamp(%s), %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (id) DO NOTHING""",
                    (
                        finding.id,
                        finding.timestamp,
                        finding.source_id,
                        finding.category,
                        finding.code,
                        finding.severity,
                        finding.message,
                        json.dumps(finding.evidence),
                        finding.recommended_action,
                    ),
                )
                connection.commit()
        except Exception:
            self.available = False
            raise
