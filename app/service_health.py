"""Dependency-free liveness/readiness server for non-HTTP workers."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


LOGGER = logging.getLogger(__name__)


class ServiceHealth:
    def __init__(self, service: str, port: int) -> None:
        self.service = service
        self.port = port
        self._ready = False
        self._details: dict[str, Any] = {"reason": "starting"}
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    def set_ready(self, ready: bool, **details: Any) -> None:
        with self._lock:
            self._ready = ready
            self._details = details

    def snapshot(self) -> tuple[bool, dict[str, Any]]:
        with self._lock:
            return self._ready, dict(self._details)

    def start(self) -> None:
        health = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
                if self.path == "/healthz":
                    self._send(200, {"status": "alive", "service": health.service})
                    return
                if self.path == "/readyz":
                    ready, details = health.snapshot()
                    self._send(
                        200 if ready else 503,
                        {
                            "status": "ready" if ready else "not_ready",
                            "service": health.service,
                            "details": details,
                        },
                    )
                    return
                self._send(404, {"status": "not_found"})

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        # This endpoint is reachable only inside the service's container network.
        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)  # nosec B104
        self.port = self._server.server_port
        thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"{self.service}-health",
            daemon=True,
        )
        thread.start()
        LOGGER.info(
            "Worker health endpoint started",
            extra={"event": "health_server_started", "component": self.service},
        )

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
