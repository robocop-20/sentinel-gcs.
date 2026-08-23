"""Prepare private key permissions, then start the mTLS API listener."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def private_copy(source: str, name: str) -> str:
    source_path = Path(source)
    if not source_path.is_file():
        raise SystemExit(f"Required TLS private key is missing: {source_path}")
    # Services run with read-only root filesystems. Their writable /tmp tmpfs
    # is deliberately the only place private-key material may be copied for
    # the strict permission checks used by OpenSSL/libpq.
    target_dir = Path("/tmp/sentinel-tls")
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
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
