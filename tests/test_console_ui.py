from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)


def test_console_ids_are_unique_and_action_queue_is_persistent():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    parser = IdCollector()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    assert 'id="event-list" class="dock-list event-list"' in html
    assert 'id="ack-justification"' in html
    assert 'id="track-detail"' in html


def test_console_uses_semantic_tokens_and_keyboard_actions():
    css = (ROOT / "operations.css").read_text(encoding="utf-8")
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    for token in (
        "--bg-void",
        "--bg-panel",
        "--border-hairline",
        "--status-nominal",
        "--status-caution",
        "--status-breach",
        "--status-selected",
    ):
        assert token in css
    assert "prefers-reduced-motion" in css
    assert "showModal()" in javascript
    assert "key==='j'" in javascript
    assert "key==='a'" in javascript
    assert "requestAnimationFrame" in javascript


def test_all_required_workspaces_have_real_view_targets():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    for workspace in (
        "flight",
        "plan",
        "camera",
        "tracks",
        "alerts",
        "sensors",
        "systems",
        "analyze",
        "evidence",
        "settings",
    ):
        assert f'data-workspace="{workspace}"' in html
        assert workspace in javascript
    assert 'data-view="flight plan"' in html
    for workspace in (
        "camera",
        "tracks",
        "alerts",
        "sensors",
        "systems",
        "analyze",
        "evidence",
        "settings",
    ):
        assert f'data-view="{workspace}"' in html


def test_console_does_not_claim_a_fake_vehicle_or_gps_fix():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    assert ">GROUND-01<" not in html
    assert "text('gps-state','3D FIX')" not in javascript
    assert "ground_speed_mps)||8" not in javascript


def test_websocket_token_is_sent_in_first_message_not_in_url():
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    backend = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "/ws/operations?access_token=" not in javascript
    assert "{type:'authenticate',access_token:accessToken}" in javascript
    assert 'authentication.get("access_token"' in backend
    assert 'websocket.query_params.get("access_token"' not in backend


def test_security_headers_are_set_by_the_api_middleware():
    backend = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for header in (
        "Content-Security-Policy",
        "Permissions-Policy",
        "Referrer-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Strict-Transport-Security",
    ):
        assert header in backend


def test_analyze_workspace_has_explicit_read_only_replay():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    backend = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for control in ("replay-start", "replay-end", "replay-load", "replay-exit"):
        assert f'id="{control}"' in html
    assert "REPLAY · READ ONLY" in javascript
    assert '@app.get("/api/history")' in backend
    assert "history_replay_read" in backend


def test_map_uses_visible_tiles_with_attribution_and_offline_fallback():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    backend = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "© OpenStreetMap contributors" in html
    assert "tile.openstreetmap.org/{z}/{x}/{y}.png" in javascript
    assert "OFFLINE TACTICAL GRID" in javascript
    assert "beginMapDrag" in javascript
    assert "zoomMapAt" in javascript
    assert "visualScale" in javascript
    assert 'id="map-scale-bar"' in html
    assert 'id="street-view-button"' in html
    assert "openStreetView" in javascript
    assert "https://tile.openstreetmap.org" in backend
    assert '"street_view_url_template"' in backend


def test_console_bootstrap_contract_connects_frontend_and_backend():
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    backend = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "fetchJson('/api/ui/bootstrap')" in javascript
    assert 'schema": "sentinel-console-bootstrap/1"' in backend
    assert '@app.get("/api/ui/bootstrap")' in backend


def test_track_and_alert_registries_have_real_filters_and_empty_states():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    for control in (
        "track-filter",
        "track-class-filter",
        "alert-filter",
        "alert-severity-filter",
    ):
        assert f'id="{control}"' in html
    assert "tableEmpty" in javascript
    assert "renderTrackWorkspace" in javascript
    assert "renderAlertWorkspace" in javascript


def test_d_backend_deployment_preserves_models_and_runtime_data():
    deployment = (ROOT / "deploy_backend_to_d.ps1").read_text(encoding="utf-8")
    assert "D:\\fpv" in deployment
    assert "'app', 'infra', 'db', 'scripts', 'secrets'" in deployment
    assert "models" not in deployment.split("$rootFiles =", 1)[1].split(")", 1)[0]
    assert "Models, evidence, camera source, .env" in deployment
    assert "--remove-orphans" in deployment


def test_split_deployment_routes_c_frontend_to_d_backend_without_second_bridge():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app.js").read_text(encoding="utf-8")
    server = (ROOT / "scripts" / "connected_frontend_server.py").read_text(encoding="utf-8")
    connector = (ROOT / "connect_c_frontend_to_d_backend.ps1").read_text(encoding="utf-8")
    tasks = (ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8")
    assert '<script src="/runtime-config.js"></script>' in html
    assert "window.SENTINEL_RUNTIME_CONFIG" in javascript
    assert "websocketUrl('/ws/operations')" in javascript
    assert "apiUrl(path)" in javascript
    assert '"mode": "connected"' in server
    assert '"websocketBaseUrl": backend' in server
    assert "proxy_api" in server
    assert "--force-recreate api" not in connector
    assert "run_mjpeg_bridge_windows.ps1" not in connector
    assert "Sentinel: Connect C Frontend to D Backend" in tasks
