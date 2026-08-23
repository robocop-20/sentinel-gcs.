"""Automatic evidence retention with a fail-closed legal-hold check."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from .config import get_settings
from .observability import configure_logging
from .persistence import Persistence
from .service_health import ServiceHealth
from .start_api import private_copy


def _inside(root: Path, candidate: str) -> Path:
    resolved_root = root.resolve()
    resolved = Path(candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError("Evidence path escaped the configured evidence directory")
    return resolved


def main() -> None:
    settings = get_settings()
    settings.validate()
    configure_logging("sentinel-evidence-retention", settings.log_level)
    logger = logging.getLogger(__name__)
    health = ServiceHealth("evidence-retention", settings.service_health_port)
    health.start()
    source_key = os.environ.get("PGSSLKEY", "/run/secrets/retention-postgres-client-key")
    os.environ["PGSSLKEY"] = private_copy(
        source_key, "retention-postgres-client-key.pem"
    )
    persistence = Persistence(
        settings.database_url,
        write_pool_size=1,
        read_pool_size=1,
    )
    evidence_root = Path(settings.evidence_dir)
    interval = max(settings.evidence_retention_interval_s, 5.0)
    try:
        while True:
            try:
                persistence.connect()
                if not persistence.available:
                    raise ConnectionError("PostGIS unavailable")
                purged = 0
                if settings.enable_evidence_retention:
                    for record in persistence.due_evidence():
                        artifact = _inside(evidence_root, record["artifact_path"])
                        manifest = _inside(evidence_root, record["manifest_path"])
                        artifact.unlink(missing_ok=True)
                        manifest.unlink(missing_ok=True)
                        persistence.mark_evidence_purged(record["evidence_id"])
                        purged += 1
                health.set_ready(
                    True,
                    retention_enabled=settings.enable_evidence_retention,
                    retention_days=settings.evidence_retention_days,
                    last_purged=purged,
                )
            except Exception as exc:
                health.set_ready(False, error=type(exc).__name__)
                logger.exception(
                    "Evidence retention pass failed",
                    extra={"event": "retention_failed", "component": "evidence"},
                )
            time.sleep(interval)
    finally:
        persistence.close()
        health.stop()


if __name__ == "__main__":
    main()
