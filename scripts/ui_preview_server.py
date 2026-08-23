"""Explicitly simulated, local-only server for offline console layout inspection.

This harness is never copied into the API image and never represents LIVE
operation. It supplies only null/empty operational values.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "sentinel-ui-preview-only"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path == "/api/auth/token":
            self._json(
                {
                    "access_token": TOKEN,
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "roles": ["viewer"],
                    "simulation": True,
                }
            )
            return
        self._json({"detail": "UI preview is read-only simulation"}, 405)

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/runtime-config.js":
            body = b"window.SENTINEL_RUNTIME_CONFIG={apiBaseUrl:window.location.origin,mode:'simulation'};"
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Sentinel-Frontend-Mode", "simulation")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/operations.css": ("operations.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        if path in assets:
            filename, content_type = assets[path]
            body = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Sentinel-Frontend-Mode", "simulation")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._authorized():
            self._json({"detail": "Authentication required"}, 401)
            return
        if path == "/api/auth/me":
            self._json({"subject": "ui-preview", "roles": ["viewer"], "kind": "user"})
        elif path == "/api/health":
            self._json({"status": "degraded", "simulation": True, "fail_safe": {"critical_path_healthy": False, "fail_safe_active": True}})
        elif path == "/api/readiness":
            self._json({"ready": False, "checks": []})
        elif path == "/api/capabilities":
            self._json({"layer_status": []})
        elif path == "/api/v2x/devices":
            self._json({"enabled": False, "tls_configured": False, "online": 0, "devices": []})
        elif path == "/api/snapshot":
            self._json(
                {
                    "simulation": True,
                    "telemetry": None,
                    "range_measurement": None,
                    "tracks": [],
                    "faces": [],
                    "vision_metrics": [],
                    "events": [],
                    "geofences": [],
                    "missions": [],
                    "v2x_devices": [],
                    "evidence_verifications": [],
                    "security_advisories": [],
                }
            )
        elif path == "/api/vision/preview.jpg":
            self._json({"detail": "No simulated video"}, 404)
        else:
            self._json({"detail": "Not found"}, 404)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 18081), Handler)
    print("Sentinel UI preview simulation: http://127.0.0.1:18081", flush=True)
    with server:
        server.serve_forever()


if __name__ == "__main__":
    main()
