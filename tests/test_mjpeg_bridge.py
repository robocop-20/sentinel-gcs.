import io
from http.server import BaseHTTPRequestHandler

import pytest

from app.mjpeg_bridge import (
    CameraSourceProvider,
    ExclusiveThreadingHTTPServer,
    jpeg_frames,
)


def test_reframes_jpegs_split_across_arbitrary_chunks():
    first = b"\xff\xd8first\xff\xd9"
    second = b"\xff\xd8second\xff\xd9"
    multipart = b"header\r\n" + first + b"\r\nnoise" + second
    assert list(jpeg_frames(io.BytesIO(multipart), chunk_size=5)) == [first, second]


def test_drops_non_jpeg_prefix_without_losing_split_soi_marker():
    jpeg = b"\xff\xd8image\xff\xd9"
    assert list(jpeg_frames(io.BytesIO(b"discard" + jpeg), chunk_size=8)) == [jpeg]


def test_camera_source_provider_reloads_atomic_file_update(tmp_path):
    source_file = tmp_path / "camera-source.txt"
    source_file.write_text("http://192.0.2.10:8080/videofeed\n", encoding="utf-8")
    provider = CameraSourceProvider("", str(source_file))

    assert provider.current() == "http://192.0.2.10:8080/videofeed"

    replacement = tmp_path / "camera-source.next"
    replacement.write_text("http://192.0.2.20:8080/videofeed\n", encoding="utf-8")
    replacement.replace(source_file)
    assert provider.current() == "http://192.0.2.20:8080/videofeed"


def test_camera_source_provider_rejects_unsupported_protocol(tmp_path):
    source_file = tmp_path / "camera-source.txt"
    source_file.write_text("rtsp://192.0.2.10:554/live\n", encoding="utf-8")

    provider = CameraSourceProvider("", str(source_file))
    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        provider.current()


def test_bridge_listener_allows_only_one_process_per_port():
    first = ExclusiveThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        port = first.server_address[1]
        with pytest.raises(OSError):
            ExclusiveThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    finally:
        first.server_close()
