"""Restart-safe local queues and duplicate suppression for critical delivery.

SQLite is deliberately used as a local spool, not as the system of record.
Messages are removed only after their downstream MQTT or PostgreSQL operation
has acknowledged success. WAL mode and FULL synchronous writes make a process
or host restart recoverable without coupling the real-time perception loop to
network availability.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


Channel = Literal["mqtt", "storage"]


class DurableQueueFull(RuntimeError):
    """The bounded local spool cannot accept another record."""


@dataclass(frozen=True)
class DurableRecord:
    id: str
    channel: Channel
    destination: str
    payload: dict[str, Any]
    qos: int
    priority: int
    attempts: int
    created_at: float
    available_at: float


class DurableQueue:
    """A small transactional outbox shared by storage and MQTT workers."""

    def __init__(
        self,
        path: str,
        *,
        max_records: int = 100_000,
        max_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        self.path = Path(path)
        self.max_records = max(max_records, 100)
        self.max_bytes = max(max_bytes, 1024 * 1024)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialise(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS durable_queue (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL CHECK(channel IN ('mqtt', 'storage')),
                    destination TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    qos INTEGER NOT NULL CHECK(qos BETWEEN 0 AND 2),
                    priority INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    available_at REAL NOT NULL,
                    last_error TEXT,
                    coalesce_key TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS durable_queue_due_idx
                    ON durable_queue(channel, available_at, priority DESC, created_at);
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    key TEXT PRIMARY KEY,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idempotency_expiry_idx
                    ON idempotency_keys(expires_at);
                """
            )

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )

    @staticmethod
    def _database_bytes(connection: sqlite3.Connection) -> int:
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        return page_count * page_size

    def enqueue(
        self,
        channel: Channel,
        destination: str,
        payload: dict[str, Any],
        *,
        qos: int = 1,
        priority: int = 50,
        coalesce_key: str | None = None,
        record_id: str | None = None,
    ) -> str:
        encoded = self._json(payload)
        now = time.time()
        item_id = record_id or str(uuid4())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                count = int(
                    connection.execute("SELECT COUNT(*) FROM durable_queue").fetchone()[
                        0
                    ]
                )
                projected_bytes = self._database_bytes(connection) + len(
                    encoded.encode("utf-8")
                )
                if count >= self.max_records or projected_bytes > self.max_bytes:
                    raise DurableQueueFull(
                        "Durable queue capacity reached; operator intervention required"
                    )
                if coalesce_key:
                    connection.execute(
                        """INSERT INTO durable_queue
                        (id, channel, destination, payload_json, qos, priority,
                         attempts, created_at, available_at, coalesce_key)
                        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                        ON CONFLICT(coalesce_key) DO UPDATE SET
                          id=excluded.id,
                          destination=excluded.destination,
                          payload_json=excluded.payload_json,
                          qos=excluded.qos,
                          priority=excluded.priority,
                          attempts=0,
                          created_at=excluded.created_at,
                          available_at=excluded.available_at,
                          last_error=NULL""",
                        (
                            item_id,
                            channel,
                            destination,
                            encoded,
                            qos,
                            priority,
                            now,
                            now,
                            coalesce_key,
                        ),
                    )
                else:
                    connection.execute(
                        """INSERT INTO durable_queue
                        (id, channel, destination, payload_json, qos, priority,
                         attempts, created_at, available_at)
                        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                        (
                            item_id,
                            channel,
                            destination,
                            encoded,
                            qos,
                            priority,
                            now,
                            now,
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return item_id

    def next_due(self, channel: Channel, *, now: float | None = None) -> DurableRecord | None:
        due = time.time() if now is None else now
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """SELECT id, channel, destination, payload_json, qos, priority,
                          attempts, created_at, available_at
                   FROM durable_queue
                   WHERE channel = ? AND available_at <= ?
                   ORDER BY priority DESC, created_at ASC LIMIT 1""",
                (channel, due),
            ).fetchone()
        if row is None:
            return None
        return DurableRecord(
            id=row["id"],
            channel=row["channel"],
            destination=row["destination"],
            payload=json.loads(row["payload_json"]),
            qos=int(row["qos"]),
            priority=int(row["priority"]),
            attempts=int(row["attempts"]),
            created_at=float(row["created_at"]),
            available_at=float(row["available_at"]),
        )

    def acknowledge(self, record_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM durable_queue WHERE id = ?", (record_id,))

    def retry(self, record_id: str, error: str, delay_s: float) -> int:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE durable_queue
                   SET attempts = attempts + 1, available_at = ?, last_error = ?
                   WHERE id = ?""",
                (time.time() + max(delay_s, 0.05), error[:500], record_id),
            )
            row = connection.execute(
                "SELECT attempts FROM durable_queue WHERE id = ?", (record_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def dead_letter(
        self,
        record: DurableRecord,
        *,
        dead_letter_topic: str,
        error: str,
    ) -> str:
        """Atomically replace an undeliverable event with a QoS-2 DLQ envelope."""
        now = time.time()
        dlq_id = str(uuid4())
        envelope = self._json(
            {
                "dead_letter_id": dlq_id,
                "original_message_id": record.id,
                "original_topic": record.destination,
                "original_payload": record.payload,
                "attempts": record.attempts + 1,
                "failed_at": now,
                "error_type": error[:200],
            }
        )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "DELETE FROM durable_queue WHERE id = ?", (record.id,)
                )
                connection.execute(
                    """INSERT INTO durable_queue
                    (id, channel, destination, payload_json, qos, priority,
                     attempts, created_at, available_at)
                    VALUES (?, 'mqtt', ?, ?, 2, 100, 0, ?, ?)""",
                    (dlq_id, dead_letter_topic, envelope, now, now),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return dlq_id

    def claim_idempotency(self, key: str, ttl_s: float) -> bool:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "DELETE FROM idempotency_keys WHERE expires_at <= ?", (now,)
                )
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO idempotency_keys(key, expires_at) VALUES (?, ?)",
                    (key, now + max(ttl_s, 1.0)),
                )
                connection.commit()
                return cursor.rowcount == 1
            except Exception:
                connection.rollback()
                raise

    def release_idempotency(self, key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM idempotency_keys WHERE key = ?", (key,))

    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT channel, COUNT(*) AS count, MIN(created_at) AS oldest,
                          SUM(CASE WHEN destination LIKE '%dead-letter%' THEN 1 ELSE 0 END)
                            AS dead_letters
                   FROM durable_queue GROUP BY channel"""
            ).fetchall()
            db_bytes = self._database_bytes(connection)
        by_channel = {
            row["channel"]: {
                "pending": int(row["count"]),
                "oldest_age_s": round(max(0.0, now - float(row["oldest"])), 3),
                "dead_letters": int(row["dead_letters"] or 0),
            }
            for row in rows
        }
        return {
            "mqtt": by_channel.get(
                "mqtt", {"pending": 0, "oldest_age_s": 0.0, "dead_letters": 0}
            ),
            "storage": by_channel.get(
                "storage", {"pending": 0, "oldest_age_s": 0.0, "dead_letters": 0}
            ),
            "database_bytes": db_bytes,
            "max_records": self.max_records,
            "max_bytes": self.max_bytes,
        }
