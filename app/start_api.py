"""Prepare private key permissions, then start the mTLS API listener."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_private_key_dir: Path | None = None


def _get_private_key_dir() -> Path:
    """Create one owner-only, process-specific writable directory for TLS keys."""
    global _private_key_dir
    if _private_key_dir is None:
        _private_key_dir = Path(tempfile.mkdtemp(prefix="sentinel-tls-"))
        _private_key_dir.chmod(0o700)
    return _private_key_dir


def private_copy(source: str, name: str) -> str:
    source_path = Path(source)
    if not source_path.is_file():
        raise SystemExit(f"Required TLS private key is missing: {source_path}")
    # Services run with read-only root filesystems. A secure process-specific
    # temporary directory is the only place private-key material may be copied
    # for the strict permission checks used by OpenSSL/libpq.
    target_dir = _get_private_key_dir()
    target = target_dir / name
    shutil.copyfile(source_path, target)
    target.chmod(0o600)
    return str(target)


def main() -> None:
    api_key = private_copy("/run/secrets/api-server-key", "api-server-key.pem")
    os.environ["MQTT_CLIENT_KEY"] = private_copy(
        "/run/secrets/api-mqtt-client-key", "api-mqtt-client-key.pem"
    )
    os.environ["PGSSLKEY"] = private_copy(
        "/run/secrets/api-postgres-client-key", "api-postgres-client-key.pem"
    )
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",  # nosec B104 - container listener is isolated by Compose networks
            "--port",
            "8080",
            "--ssl-keyfile",
            api_key,
            "--ssl-certfile",
            "/run/secrets/api-server-cert",
            "--ssl-ca-certs",
            "/run/secrets/tls-ca",
            "--ssl-cert-reqs",
            "2",
        ],
    )


if __name__ == "__main__":
    main()
