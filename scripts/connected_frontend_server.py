"""Serve the C: operations console while it connects to an explicit backend.

This is a static frontend server, not an API simulator or reverse proxy. The
browser connects directly to the configured backend for authentication, REST,
camera preview, and the operations WebSocket.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/operations.css": ("operations.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def validated_backend(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Backend must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Backend URL cannot contain credentials, query, or fragment")
    return f"{parsed.scheme}://{parsed.netloc}"


def handler_for(backend: str, frontend: str):
    parsed = urlparse(backend)
    websocket_origin = (
        f"{'wss' if parsed.scheme == 'https' else 'ws'}://{parsed.netloc}"
    )
    runtime_body = (
        "window.SENTINEL_RUNTIME_CONFIG="
        + json.dumps(
            {
                "apiBaseUrl": frontend,
                "websocketBaseUrl": backend,
                "mode": "connected",
            }
        )
        + ";"
    ).encode("utf-8")
    csp = (
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
        "style-src 'self'; script-src 'self'; "
        "img-src 'self' data: blob: https://tile.openstreetmap.org; "
        f"connect-src 'self' {backend} {websocket_origin};"
    )

    class ConnectedFrontendHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A003
            return

        def send_common_headers(self, content_type: str, length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", csp)
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Sentinel-Frontend-Mode", "connected")

        def proxy_api(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > 8 * 1024 * 1024:
                self.send_error(413, "Request body too large")
                return
            body = self.rfile.read(length) if length else None
            headers = {}
            for name in ("Authorization", "Content-Type", "Accept"):
                value = self.headers.get(name)
                if value:
                    headers[name] = value
            request = Request(
                backend + self.path,
                data=body,
                headers=headers,
                method=self.command,
            )
            try:
                response = urlopen(request, timeout=20)
            except HTTPError as error:
                response = error
            except URLError:
                self.send_error(502, "D backend unavailable")
                return
            with response:
                payload = response.read()
                self.send_response(response.status)
                self.send_common_headers(
                    response.headers.get("Content-Type", "application/octet-stream"),
                    len(payload),
                )
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path.startswith("/api/"):
                self.proxy_api()
            else:
                self.send_error(404, "Not found")

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                self.proxy_api()
                return
            if path == "/healthz":
                body = json.dumps(
                    {
                        "status": "ready",
                        "service": "sentinel-connected-frontend",
                        "backend": backend,
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_common_headers("application/json", len(body))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/runtime-config.js":
                self.send_response(200)
                self.send_common_headers(
                    "text/javascript; charset=utf-8", len(runtime_body)
                )
                self.end_headers()
                self.wfile.write(runtime_body)
                return
            asset = ASSETS.get(path)
            if asset is None:
                self.send_error(404, "Not found")
                return
            filename, content_type = asset
            body = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_common_headers(content_type, len(body))
            self.end_headers()
            self.wfile.write(body)

    return ConnectedFrontendHandler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:8080")
    parser.add_argument("--port", type=int, default=18082)
    args = parser.parse_args()
    backend = validated_backend(args.backend)
    frontend = f"http://127.0.0.1:{args.port}"
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), handler_for(backend, frontend)
    )
    print(
        f"Sentinel connected frontend: http://127.0.0.1:{args.port} -> {backend}",
        flush=True,
    )
    with server:
        server.serve_forever()


if __name__ == "__main__":
    main()
