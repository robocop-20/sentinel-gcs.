"""Small transactional SQL migration runner for the API-owned schema."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from psycopg import Connection

MIGRATION_ROOT = Path(__file__).resolve().parent / "sql_migrations"
STATEMENT_MARKER = "-- sentinel:statement"


def apply_migrations(connection: Connection[Any]) -> list[str]:
    """Apply immutable, checksummed migrations under a database advisory lock."""
    connection.execute("SELECT pg_advisory_xact_lock(731954121)")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        sha256 CHAR(64) NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    applied: list[str] = []
    for path in sorted(MIGRATION_ROOT.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        row = connection.execute(
            "SELECT sha256 FROM schema_migrations WHERE version = %s", (path.name,)
        ).fetchone()
        if row is not None:
            if row[0].strip() != digest:
                raise RuntimeError(f"Applied migration checksum changed: {path.name}")
            continue
        statements = [item.strip() for item in sql.split(STATEMENT_MARKER) if item.strip()]
        for statement in statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
            (path.name, digest),
        )
        applied.append(path.name)
    return applied

