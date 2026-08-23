"""Windows-host MJPEG bridge for cameras unreachable from Docker Desktop's VM.

It deliberately does no image processing: it is an input-adapter boundary.  A
Docker vision worker connects to this local bridge while the bridge itself
reads the camera over the Windows Wi-Fi route.
"""

import logging
import os
import secrets
import json
import socket
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from .observability import configure_logging


LOGGER = logging.getLogger(__name__)


SOURCE_URL = os.environ.get("MJPEG_SOURCE_URL", "")
SOURCE_FILE = os.environ.get("MJPEG_SOURCE_FILE", "")
# Docker Desktop reaches this Windows-host adapter over a non-loopback address;
# /videofeed still requires a constant-time checked random token.
LISTEN_HOST = os.environ.get("MJPEG_LISTEN_HOST", "0.0.0.0")  # nosec B104
LISTEN_PORT = int(os.environ.get("MJPEG_LISTEN_PORT", "8090"))
ACCESS_TOKEN = os.environ.get("MJPEG_BRIDGE_TOKEN", "")
INSTANCE_ID = os.environ.get("MJPEG_BRIDGE_INSTANCE_ID", "unidentified")
OUTPUT_BOUNDARY = b"sentinel-frame"
UPSTREAM_RECONNECT_DELAY_S = 0.25


class BridgeMetrics:
    """Thread-safe bridge health with no camera URL or token disclosure."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.frames = 0
        self.upstream_errors = 0
        self.last_frame_at: float | None = None
        self.source_reloads = 0

    def record_frame(self) -> None:
        with self._lock:
            self.frames += 1
            self.last_frame_at = time.time()

    def record_error(self) -> None:
        with self._lock:
            self.upstream_errors += 1

    def record_reload(self) -> None:
        with self._lock:
            self.source_reloads += 1

    def health(self) -> dict:
        with self._lock:
            recent = (
                self.last_frame_at is not None and time.time() - self.last_frame_at <= 5
            )
            return {
                "status": "ok" if recent else "waiting_for_frame",
                "instance_id": INSTANCE_ID,
                "frames_forwarded": self.frames,
                "upstream_errors": self.upstream_errors,
                "source_reloads": self.source_reloads,
                "last_frame_at": self.last_frame_at,
            }


METRICS = BridgeMetrics()


class CameraSourceProvider:
    """Return a validated camera URL and hot-reload an optional source file."""

    def __init__(self, fallback_url: str, source_file: str = "") -> None:
        self._fallback_url = fallback_url.strip()
        self._source_file = Path(source_file).resolve() if source_file else None
        self._lock = threading.Lock()
        self._file_signature: tuple[int, int] | None = None
        self._source_url = ""

    @staticmethod
    def _validate(source: str) -> str:
        candidate = source.strip().lstrip("\ufeff")
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("camera source must be an HTTP(S) endpoint")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("camera source port is invalid") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("camera source port is outside 1-65535")
        return candidate

    def current(self) -> str:
        with self._lock:
            if self._source_file is None:
                if not self._source_url:
                    self._source_url = self._validate(self._fallback_url)
                return self._source_url

            try:
                stat = self._source_file.stat()
            except OSError as exc:
                raise ValueError("camera source file is unavailable") from exc
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature != self._file_signature:
                source = next(
                    (
                        line.strip()
                        for line in self._source_file.read_text(
                            encoding="utf-8-sig"
                        ).splitlines()
                        if line.strip() and not line.lstrip().startswith("#")
                    ),
                    "",
                )
                validated = self._validate(source)
                changed = bool(self._source_url and validated != self._source_url)
                self._source_url = validated
                self._file_signature = signature
                if changed:
                    METRICS.record_reload()
                    LOGGER.info(
                        "Camera source configuration reloaded",
                        extra={"event": "camera_source_reloaded"},
                    )
            return self._source_url


SOURCE_PROVIDER = CameraSourceProvider(SOURCE_URL, SOURCE_FILE)


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """Single-owner listener, including on Windows.

    ``SO_REUSEADDR`` has different semantics on Windows and can permit two
    camera bridges to bind the same port. Requests are then distributed between
    processes with independent upstream state. Use Windows' exclusive-address
    option when available and disable address reuse everywhere else.
    """

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def jpeg_frames(stream, chunk_size: int = 4096):
    """Extract complete JPEG images from arbitrary multipart/chunked input.

    IP cameras differ in multipart headers and chunk boundaries. Re-framing at
    JPEG SOI/EOI markers makes OpenCV receive valid complete MJPEG parts even
    when the upstream boundary is fragmented or absent.
    """
    buffer = bytearray()
    while chunk := stream.read(chunk_size):
        buffer.extend(chunk)
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                # Keep one trailing byte in case SOI is split across chunks.
                del buffer[:-1]
                break
            if start:
                del buffer[:start]
            end = buffer.find(b"\xff\xd9", 2)
            if end < 0:
                break
            yield bytes(buffer[: end + 2])
            del buffer[: end + 2]


class MjpegBridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A003 - BaseHTTPRequestHandler signature
        # Never write the token-bearing request target to logs.
        LOGGER.info(
            "MJPEG bridge request",
            extra={
                "event": "bridge_request",
                "method": self.command,
                "path": urlparse(self.path).path,
            },
        )

    def do_GET(self):  # noqa: N802 - HTTP handler API
        parsed_path = urlparse(self.path)
        if parsed_path.path in {"/health", "/healthz", "/readyz"}:
            payload = METRICS.health()
            if parsed_path.path == "/healthz":
                payload = {
                    "status": "alive",
                    "service": "sentinel-mjpeg-bridge",
                    "instance_id": INSTANCE_ID,
                }
            status = (
                503
                if parsed_path.path == "/readyz" and payload["status"] != "ok"
                else 200
            )
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path != "/videofeed":
            self.send_error(404, "Use /videofeed")
            return
        supplied_token = parse_qs(parsed_path.query).get("token", [""])[0]
        if not ACCESS_TOKEN or not secrets.compare_digest(supplied_token, ACCESS_TOKEN):
            self.send_error(403, "Invalid bridge token")
            return
        try:
            source_url = SOURCE_PROVIDER.current()
        except ValueError:
            METRICS.record_error()
            self.send_error(503, "Camera source configuration is invalid")
            return
        if not source_url:
            self.send_error(503, "MJPEG_SOURCE_URL is not configured")
            return
        headers_sent = False
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # IP Webcam can end an MJPEG response at any time.  Keep the
            # downstream response alive and reconnect only the upstream leg;
            # otherwise OpenCV repeatedly loses its decoder and ByteTrack has
            # no continuous sequence from which to form a stable ID.
            while True:
                try:
                    source_url = SOURCE_PROVIDER.current()
                except ValueError:
                    METRICS.record_error()
                    if not headers_sent:
                        self.send_error(503, "Camera source configuration is invalid")
                    return
                try:
                    request = Request(
                        source_url,
                        headers={
                            "User-Agent": "Sentinel-MJPEG-Bridge/1.0",
                            "Accept": "multipart/x-mixed-replace, image/jpeg;q=0.9",
                            "Cache-Control": "no-cache",
                            "Connection": "close",
                        },
                    )
                    # The source provider restricts the URL to HTTP(S).
                    with urlopen(request, timeout=10) as upstream:  # nosec B310
                        if not headers_sent:
                            self.send_response(200)
                            self.send_header(
                                "Content-Type",
                                f"multipart/x-mixed-replace; boundary={OUTPUT_BOUNDARY.decode('ascii')}",
                            )
                            self.send_header("Cache-Control", "no-store")
                            self.send_header("Pragma", "no-cache")
                            self.send_header("Connection", "keep-alive")
                            self.end_headers()
                            headers_sent = True
                        forwarded = 0
                        source_changed = False
                        for jpeg in jpeg_frames(upstream):
                            # A source-file change should reconnect upstream
                            # without tearing down the vision worker's stream.
                            try:
                                configured_source = SOURCE_PROVIDER.current()
                            except ValueError:
                                METRICS.record_error()
                                return
                            if configured_source != source_url:
                                source_changed = True
                                break
                            part = (
                                b"--"
                                + OUTPUT_BOUNDARY
                                + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                + str(len(jpeg)).encode("ascii")
                                + b"\r\n\r\n"
                                + jpeg
                                + b"\r\n"
                            )
                            self.wfile.write(part)
                            self.wfile.flush()
                            METRICS.record_frame()
                            forwarded += 1
                        if not source_changed:
                            # EOF or an incomplete multipart body.  Retrying
                            # preserves the valid downstream MJPEG framing.
                            METRICS.record_error()
                            LOGGER.warning(
                                "Camera upstream stream ended; reconnecting",
                                extra={
                                    "event": "upstream_stream_ended",
                                    "component": "camera_ingest",
                                    "frames_forwarded": forwarded,
                                },
                            )
                except (BrokenPipeError, ConnectionResetError):
                    return
                except (URLError, OSError, HTTPException):
                    METRICS.record_error()
                    LOGGER.warning(
                        "Camera upstream unavailable; reconnecting",
                        extra={
                            "event": "upstream_unavailable",
                            "component": "camera_ingest",
                        },
                    )
                    if not headers_sent:
                        self.send_error(502, "Camera upstream unavailable")
                        return
                time.sleep(UPSTREAM_RECONNECT_DELAY_S)
        except (BrokenPipeError, ConnectionResetError):
            return


def main():
    if not ACCESS_TOKEN:
        raise SystemExit("MJPEG_BRIDGE_TOKEN is required")
    try:
        SOURCE_PROVIDER.current()
    except ValueError as exc:
        raise SystemExit(f"Invalid camera source configuration: {exc}") from exc
    configure_logging("sentinel-mjpeg-bridge")
    try:
        # The host bridge must accept the Docker Desktop VM connection; token
        # authentication protects the video endpoint.
        server = ExclusiveThreadingHTTPServer(
            (LISTEN_HOST, LISTEN_PORT), MjpegBridgeHandler
        )  # nosec B104
    except OSError as exc:
        raise SystemExit(
            f"Cannot start MJPEG bridge on {LISTEN_HOST}:{LISTEN_PORT}; "
            "another bridge may already be running. Stop it before retrying."
        ) from exc
    LOGGER.info(
        "MJPEG bridge started",
        extra={"event": "bridge_started", "component": "camera_ingest"},
    )
    with server:
        server.serve_forever()


if __name__ == "__main__":
    main()
