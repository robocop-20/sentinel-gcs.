"""Thin API/orchestration layer; compute, rules, storage and transport run separately."""

import asyncio
import base64
import json
import logging
import math
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4
from fastapi import (
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from .auth import (
    AuthenticationError,
    AuthManager,
    Principal,
    ROLE_ADMINISTRATOR,
    ROLE_ANALYST,
    ROLE_AUDITOR,
    ROLE_OPERATOR,
    ROLE_SERVICE,
    ROLE_SYSTEM_ADMIN,
    ROLE_VIEWER,
)
from .config import get_settings
from .durable_queue import DurableQueue
from .events import EventEngine
from .evidence_crypto import load_evidence_key
from .evidence_integrity import verify_evidence_files
from .failsafe import assess_fail_safe
from .geofence import geofence_version
from .http_limits import RequestBodyLimitMiddleware
from .llm_verifier import LlmVerificationWorker
from .mission import event_transition_allowed, validate_mission
from .metrics import SentinelMetrics
from .mqtt import MqttPublisher
from .observability import (
    RequestTimer,
    bind_correlation_id,
    bind_trace_context,
    configure_logging,
    correlation_id,
    current_traceparent,
    new_correlation_id,
    new_trace_context,
    reset_correlation_id,
    reset_trace_context,
)
from .persistence import Persistence
from .pipeline import LayeredPipeline
from .risk_engine import RiskEngine
from .security_adviser import SecurityAdvisoryWorker
from .security_monitor import SecurityMonitor
from .schemas import (
    Acknowledge,
    CameraSourceUpdate,
    DetectionBatch,
    DeviceEndpointRegistration,
    Event,
    Geofence,
    RangeMeasurement,
    Telemetry,
    EvidenceRequest,
    EvidenceVerification,
    EventTransition,
    MissionChange,
    MissionDelete,
    MissionPrepareUpload,
    MissionRecord,
    SecurityAdvisory,
    SecurityFinding,
    V2XEnvelope,
    V2XHeartbeat,
    VisionMetrics,
    VisionPreview,
    LegalHoldUpdate,
)
from .state import OperationsState
from .v2x import v2x_heartbeat_validation_reason, v2x_validation_reason

settings = get_settings()
configure_logging("sentinel-api", settings.log_level)
LOGGER = logging.getLogger(__name__)
auth_manager = AuthManager(settings)
state = OperationsState(
    active_track_ttl_s=settings.active_track_ttl_s,
    track_occluded_after_s=settings.track_occluded_after_s,
    track_temporarily_lost_after_s=settings.track_temporarily_lost_after_s,
    track_reacquired_after_s=settings.track_reacquired_after_s,
    v2x_device_offline_s=settings.v2x_device_offline_s,
)
event_engine = EventEngine()
risk_engine = RiskEngine(
    settings.risk_timezone, settings.risk_quiet_start_hour, settings.risk_quiet_end_hour
)
persistence = Persistence(
    settings.database_url,
    write_pool_size=settings.database_write_pool_size,
    read_pool_size=settings.database_read_pool_size,
)
mqtt = MqttPublisher(settings)
metrics = SentinelMetrics()
security_monitor = SecurityMonitor(settings)
pipeline: LayeredPipeline | None = None
durable_queue: DurableQueue | None = None
llm_worker: LlmVerificationWorker | None = None
security_advisory_worker: SecurityAdvisoryWorker | None = None
security_watchdog_task: asyncio.Task | None = None
WEB_ROOT = Path(__file__).resolve().parent.parent
OPERATOR_CONFIG_DIRECTORY = Path(os.getenv("OPERATOR_CONFIG_DIRECTORY", "/config"))
CAMERA_SOURCE_FILE = OPERATOR_CONFIG_DIRECTORY / "camera-source.txt"
DEVICE_REGISTRY_FILE = OPERATOR_CONFIG_DIRECTORY / "operator-assets.json"


def _normalise_http_endpoint(value: str, *, primary_camera: bool = False) -> str:
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(422, "Use a valid HTTP or HTTPS endpoint")
    if parsed.username or parsed.password:
        raise HTTPException(422, "Endpoints must not contain embedded credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(422, "Endpoint port is invalid") from exc
    if port is not None and not 1 <= port <= 65535:
        raise HTTPException(422, "Endpoint port is outside the valid range")
    path = parsed.path or ("/videofeed" if primary_camera else "/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def _atomic_write(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        LOGGER.exception("operator configuration write failed", extra={"path": str(path)})
        raise HTTPException(503, "Operator configuration storage is unavailable") from exc


def _registered_assets() -> list[dict[str, str]]:
    try:
        if not DEVICE_REGISTRY_FILE.is_file():
            return []
        payload = json.loads(DEVICE_REGISTRY_FILE.read_text(encoding="utf-8"))
        assets = payload.get("assets", []) if isinstance(payload, dict) else []
        return [item for item in assets if isinstance(item, dict)][:32]
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("operator asset registry could not be read")
        return []
PUBLIC_PATHS = {
    "/",
    "/styles.css",
    "/operations.css",
    "/app.js",
    "/healthz",
    "/readyz",
    "/metrics",
    "/api/auth/token",
    "/api/auth/service-token",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}
OPERATOR_ROLES = {ROLE_OPERATOR, ROLE_ADMINISTRATOR, ROLE_SYSTEM_ADMIN}
VIEWER_ROLES = {
    ROLE_VIEWER,
    ROLE_OPERATOR,
    ROLE_ANALYST,
    ROLE_AUDITOR,
    ROLE_ADMINISTRATOR,
    ROLE_SYSTEM_ADMIN,
}
SERVICE_PATHS = {
    "/api/telemetry",
    "/api/range",
    "/api/detections",
    "/api/vision/metrics",
    "/api/vision/preview",
    "/api/v2x/events",
    "/api/v2x/heartbeats",
    "/api/evidence/verifications",
}
_rate_windows: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = asyncio.Lock()


async def on_track(track: dict) -> None:
    track = state.record_track(track)
    metrics.record_track(track)
    await state.broadcast("track", track)
    # Gemini receives only this sanitised local safety summary. It receives no
    # person image, body pose vector, face, location, or tracking control.
    fall = track.get("fall")
    if isinstance(fall, dict):
        await on_security_finding(
            SecurityFinding(
                id=str(uuid4()),
                timestamp=float(track.get("timestamp", time.time())),
                source_id=str(track.get("source", "unknown-camera")),
                category="physical_safety",
                code="possible_fall",
                severity="warning",
                message="A local pose-and-time model reported a possible fall for an anonymous track.",
                evidence={
                    "fall_confidence": float(fall.get("confidence", 0.0)),
                    "sustained_frames": float(fall.get("sustained_frames", 0)),
                },
                recommended_action=(
                    "Ask an operator to visually check the camera scene and follow the "
                    "approved welfare and safety procedure."
                ),
            )
        )


async def on_faces(face_data: dict) -> None:
    state.faces[face_data["source"]] = face_data
    await state.broadcast("face", face_data)


async def on_event(event: Event) -> None:
    state.events.append(event)
    metrics.record_event(event)
    await state.broadcast("event", event.model_dump(mode="json"))


async def on_evidence_request(request: EvidenceRequest) -> None:
    state.record_evidence_request(request)
    await state.broadcast("evidence_request", request.model_dump(mode="json"))
    if llm_worker:
        llm_worker.submit(request)


async def on_evidence_verification(verification: EvidenceVerification) -> bool:
    """Record a review only while its bounded evidence request is still valid."""
    request = next(
        (
            item
            for item in state.evidence_requests
            if item.request_id == verification.request_id
        ),
        None,
    )
    if request is None or time.time() > request.expires_at:
        return False
    # Deliberately isolated: verification cannot affect score, severity,
    # geofence state, or critical-alert dispatch.
    state.record_evidence_verification(verification)
    metrics.record_llm_review(verification, request.requested_at)
    payload = verification.model_dump()
    require_pipeline().queue_transport("ground/evidence/verifications", payload)
    await state.broadcast("evidence_verification", payload)
    return True


async def on_security_advisory(advisory: SecurityAdvisory) -> None:
    """Store/broadcast a text summary without granting it any control authority."""
    state.record_security_advisory(advisory)
    payload = advisory.model_dump(mode="json")
    require_pipeline().queue_transport(settings.security_advisories_topic, payload)
    await state.broadcast("security_advisory", payload)


async def on_security_finding(finding: SecurityFinding) -> None:
    """Persist and publish an advisory integrity symptom independently of events."""
    state.record_security_finding(finding)
    try:
        await asyncio.to_thread(persistence.save_security_finding, finding)
    except Exception:
        # The local state and MQTT alert remain useful while storage reconnects.
        LOGGER.exception(
            "Security finding persistence failed",
            extra={
                "event": "security_finding_persistence_failed",
                "component": "storage",
                "finding_id": finding.id,
            },
        )
    payload = finding.model_dump(mode="json")
    require_pipeline().queue_transport(settings.security_findings_topic, payload)
    await state.broadcast("security_finding", payload)
    if security_advisory_worker:
        security_advisory_worker.submit(state.security_findings[-8:])


async def security_watchdog() -> None:
    """Periodic freshness detection; it never sends a command to any device."""
    while True:
        await asyncio.sleep(max(settings.security_monitor_interval_s, 0.2))
        if settings.enable_security_monitor:
            for finding in security_monitor.check_telemetry_freshness(state.telemetry):
                await on_security_finding(finding)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline, durable_queue, llm_worker, security_advisory_worker
    global security_watchdog_task
    settings.validate()
    auth_manager.validate_configuration()
    for _ in range(6):
        await asyncio.to_thread(persistence.connect)
        if persistence.available:
            break
        await asyncio.sleep(2)
    llm_worker = LlmVerificationWorker(settings, on_evidence_verification)
    await llm_worker.start()
    security_advisory_worker = SecurityAdvisoryWorker(settings, on_security_advisory)
    await security_advisory_worker.start()
    durable_queue = DurableQueue(
        settings.durable_queue_path,
        max_records=settings.durable_queue_max_records,
        max_bytes=settings.durable_queue_max_bytes,
    )
    pipeline = LayeredPipeline(
        settings,
        state,
        event_engine,
        risk_engine,
        on_track,
        on_faces,
        on_event,
        on_evidence_request,
        persistence.save_track,
        persistence.save_event,
        lambda track: persistence.save_evidence(
            track, settings.evidence_retention_days
        ),
        mqtt.publish,
        durable_queue,
    )
    await pipeline.start()
    if settings.enable_security_monitor:
        security_watchdog_task = asyncio.create_task(
            security_watchdog(), name="security-integrity-watchdog"
        )
    try:
        yield
    finally:
        if security_watchdog_task:
            security_watchdog_task.cancel()
            await asyncio.gather(security_watchdog_task, return_exceptions=True)
        await pipeline.stop()
        await llm_worker.stop()
        await security_advisory_worker.stop()
        mqtt.close()
        persistence.close()


app = FastAPI(title="Sentinel FPV Ground Station", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
)
app.add_middleware(
    RequestBodyLimitMiddleware, max_body_size=settings.request_body_limit_bytes
)


def _bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Bearer token is required")
    return token.strip()


def _required_roles(path: str, method: str) -> set[str]:
    if path.startswith("/api/audit"):
        return {ROLE_AUDITOR, ROLE_ADMINISTRATOR, ROLE_SYSTEM_ADMIN}
    if path.startswith("/api/evidence/") and path.endswith("/legal-hold"):
        return {ROLE_ADMINISTRATOR, ROLE_SYSTEM_ADMIN}
    if path in SERVICE_PATHS and method == "POST":
        return {ROLE_SERVICE, ROLE_SYSTEM_ADMIN}
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return OPERATOR_ROLES
    return VIEWER_ROLES


async def _within_rate_limit(key: str, limit: int) -> bool:
    now = time.monotonic()
    async with _rate_lock:
        window = _rate_windows[key]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    request_id = new_correlation_id(request.headers.get("X-Correlation-ID"))
    token = bind_correlation_id(request_id)
    trace_tokens = bind_trace_context(
        *new_trace_context(request.headers.get("traceparent"))
    )
    timer = RequestTimer()
    try:
        client_ip = request.client.host if request.client else "unknown"
        auth_path = request.url.path in {"/api/auth/token", "/api/auth/service-token"}
        if auth_path:
            rate_limit = settings.auth_rate_limit_per_minute
        elif request.url.path in SERVICE_PATHS and request.method == "POST":
            # Service paths are authenticated with a dedicated service
            # credential when auth is enabled.  Keep their higher but finite
            # throughput budget separate from interactive API requests.
            rate_limit = settings.service_rate_limit_per_minute
        elif request.url.path == "/api/vision/preview.jpg":
            rate_limit = settings.preview_rate_limit_per_minute
        else:
            rate_limit = settings.api_rate_limit_per_minute
        if not await _within_rate_limit(
            f"{client_ip}:{request.url.path}", max(rate_limit, 1)
        ):
            response = JSONResponse(
                status_code=429,
                content={"detail": "Request rate limit exceeded"},
                headers={"Retry-After": "60"},
            )
            response.headers["X-Correlation-ID"] = request_id
            response.headers["traceparent"] = current_traceparent()
            return response
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("Content-Length")
            if (
                content_length
                and content_length.isdecimal()
                and int(content_length) > settings.request_body_limit_bytes
            ):
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "Request body exceeds configured limit"},
                )
                response.headers["X-Correlation-ID"] = request_id
                response.headers["traceparent"] = current_traceparent()
                return response
        if settings.auth_enabled and request.url.path not in PUBLIC_PATHS:
            try:
                principal = auth_manager.decode_token(_bearer_token(request))
            except AuthenticationError:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing access token"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
                response.headers["X-Correlation-ID"] = request_id
                response.headers["traceparent"] = current_traceparent()
                return response
            if not principal.permits(_required_roles(request.url.path, request.method)):
                response = JSONResponse(
                    status_code=403, content={"detail": "Insufficient role"}
                )
                response.headers["X-Correlation-ID"] = request_id
                response.headers["traceparent"] = current_traceparent()
                return response
            request.state.principal = principal
        else:
            request.state.principal = Principal(
                "anonymous", frozenset({ROLE_SYSTEM_ADMIN}), "user", ""
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; "
            "script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob: https://tile.openstreetmap.org; "
            "connect-src 'self' ws: wss:"
        )
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Correlation-ID"] = request_id
        response.headers["traceparent"] = current_traceparent()
        route = request.scope.get("route")
        route_label = getattr(route, "path", request.url.path)
        metrics.record_http(
            request.method, route_label, response.status_code, timer.elapsed_ms
        )
        LOGGER.info(
            "HTTP request completed",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": timer.elapsed_ms,
            },
        )
        return response
    except Exception:
        metrics.record_http(request.method, request.url.path, 500, timer.elapsed_ms)
        LOGGER.exception(
            "HTTP request failed",
            extra={
                "event": "http_request_failed",
                "method": request.method,
                "path": request.url.path,
                "duration_ms": timer.elapsed_ms,
            },
        )
        raise
    finally:
        reset_trace_context(trace_tokens)
        reset_correlation_id(token)


def require_pipeline() -> LayeredPipeline:
    if pipeline is None:
        raise HTTPException(503, "Processing pipeline is starting")
    return pipeline


async def record_audit(
    principal: Principal,
    action: str,
    target: str,
    justification: str,
    metadata: dict | None = None,
    *,
    required: bool = True,
) -> None:
    try:
        await asyncio.to_thread(
            persistence.append_audit,
            actor=principal.subject,
            roles=sorted(principal.roles),
            action=action,
            target=target,
            justification=justification,
            correlation_id=correlation_id(),
            metadata=metadata,
        )
    except Exception:
        LOGGER.exception(
            "Audit append failed",
            extra={"event": "audit_append_failed", "component": "audit"},
        )
        if required:
            raise HTTPException(503, "Audit service unavailable; action rejected")


@app.post("/api/auth/token", include_in_schema=False)
async def operator_token(form: OAuth2PasswordRequestForm = Depends()):
    try:
        subject, roles = await asyncio.to_thread(
            auth_manager.authenticate_user, form.username, form.password
        )
        principal = Principal(subject, roles, "user", "")
        await record_audit(
            principal,
            "authentication_succeeded",
            "operator-session",
            "Operator completed credential authentication",
        )
        return auth_manager.issue_token(subject, roles, "user")
    except AuthenticationError:
        LOGGER.warning(
            "Operator authentication failed",
            extra={
                "event": "authentication_failed",
                "subject": form.username,
                "kind": "user",
            },
        )
        failed = Principal(
            form.username[:96] or "unknown", frozenset({ROLE_VIEWER}), "user", ""
        )
        await record_audit(
            failed,
            "authentication_failed",
            "operator-session",
            "Operator credential authentication failed",
            required=False,
        )
        raise HTTPException(
            401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"}
        )


@app.post("/api/auth/service-token", include_in_schema=False)
async def service_token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
):
    if grant_type != "client_credentials":
        raise HTTPException(400, "Unsupported grant_type")
    try:
        subject, roles = await asyncio.to_thread(
            auth_manager.authenticate_service, client_id, client_secret
        )
        principal = Principal(subject, roles, "service", "")
        await record_audit(
            principal,
            "service_authentication_succeeded",
            "service-session",
            "Internal service completed client-credentials authentication",
        )
        return auth_manager.issue_token(subject, roles, "service")
    except AuthenticationError:
        LOGGER.warning(
            "Service authentication failed",
            extra={
                "event": "authentication_failed",
                "subject": client_id,
                "kind": "service",
            },
        )
        failed = Principal(
            client_id[:96] or "unknown", frozenset({ROLE_SERVICE}), "service", ""
        )
        await record_audit(
            failed,
            "service_authentication_failed",
            "service-session",
            "Internal service client-credentials authentication failed",
            required=False,
        )
        raise HTTPException(
            401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"}
        )


@app.get("/api/auth/me", include_in_schema=False)
async def auth_me(request: Request):
    principal: Principal = request.state.principal
    return {
        "subject": principal.subject,
        "roles": sorted(principal.roles),
        "kind": principal.kind,
    }


def fail_safe_report(active_pipeline: LayeredPipeline | None = None) -> dict:
    active = active_pipeline or require_pipeline()
    object_llm_health = llm_worker.health() if llm_worker else {"enabled": False}
    security_llm_health = (
        security_advisory_worker.health()
        if security_advisory_worker
        else {"enabled": False}
    )
    return assess_fail_safe(
        settings,
        state,
        active.health(),
        mqtt_connected=mqtt.connected,
        storage_available=persistence.available,
        llm_health=object_llm_health,
        security_llm_health=security_llm_health,
        security_health=security_monitor.health(),
    )


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Process liveness only; dependencies are deliberately excluded."""
    return {"status": "alive", "service": "sentinel-api"}


@app.get("/readyz", include_in_schema=False)
async def readyz():
    """Service readiness for orchestration, distinct from field acceptance."""
    pipeline_health = pipeline.health() if pipeline else None
    workers_ready = bool(
        pipeline_health
        and pipeline_health.get("workers")
        and all(pipeline_health["workers"].values())
    )
    checks = {
        "pipeline_workers": workers_ready,
        "postgis": persistence.available,
        "mqtt": mqtt.connected,
    }
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "service": "sentinel-api",
            "checks": checks,
        },
    )


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    """Internal mTLS scrape target; the browser gateway blocks this path."""
    active_pipeline = require_pipeline()
    metrics.update_runtime(
        mqtt_connected=mqtt.connected,
        postgis_available=persistence.available,
        pipeline_health=active_pipeline.health(),
        llm_health=llm_worker.health() if llm_worker else {"enabled": False},
    )
    body, content_type = metrics.render()
    return Response(content=body, headers={"Content-Type": content_type})


@app.get("/api/health")
async def health():
    active_pipeline = require_pipeline()
    fail_safe = fail_safe_report(active_pipeline)
    return {
        "status": "ok" if fail_safe["critical_path_healthy"] else "degraded",
        "mqtt": mqtt.connected,
        "postgis": persistence.available,
        "pipeline": active_pipeline.health(),
        "llm_verifier": llm_worker.health() if llm_worker else {"enabled": False},
        "security_monitor": security_monitor.health(),
        "security_llm_adviser": security_advisory_worker.health()
        if security_advisory_worker
        else {"enabled": False},
        "v2x": {
            "enabled": settings.enable_v2x,
            "devices": state.v2x_device_snapshot(),
            "tls_configured": settings.mqtt_tls_enabled,
        },
        "fail_safe": {
            key: fail_safe[key]
            for key in (
                "status",
                "fail_safe_active",
                "critical_path_healthy",
                "automatic_device_actions",
            )
        },
    }


@app.get("/api/history")
async def history_replay(
    request: Request,
    start: float = Query(..., ge=0),
    end: float = Query(..., ge=0),
    limit: int = Query(500, ge=1, le=10000),
):
    """Read a bounded historical timeline without mutating live operations state."""
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise HTTPException(422, "History start/end range is invalid")
    if end - start > settings.history_query_max_span_s:
        raise HTTPException(
            422,
            f"History range exceeds {settings.history_query_max_span_s:g} seconds",
        )
    bounded_limit = min(limit, settings.history_query_max_records)
    try:
        records = await asyncio.to_thread(
            persistence.query_history, start, end, bounded_limit
        )
    except Exception as exc:
        LOGGER.warning(
            "Historical replay query failed",
            extra={"event": "history_query_failed", "error_type": type(exc).__name__},
        )
        raise HTTPException(503, "Historical storage is unavailable") from exc
    principal: Principal = request.state.principal
    await record_audit(
        principal,
        "history_replay_read",
        "operational-history",
        "Authorized operator requested a bounded read-only replay window",
        metadata={"start": start, "end": end, "records": len(records)},
    )
    return {
        "schema": "sentinel-history-replay/1",
        "mode": "REPLAY",
        "start": start,
        "end": end,
        "records": records,
    }


@app.get("/api/failsafe")
async def failsafe():
    """Return explicit per-layer containment status without changing any system state."""
    return fail_safe_report()


@app.get("/api/readiness")
async def readiness():
    """Return measured field-acceptance checks; never an automatic approval."""
    latest = max(
        state.vision_metrics.values(), key=lambda item: item.timestamp, default=None
    )
    metrics_age_s = max(0.0, time.time() - latest.timestamp) if latest else None
    processing = bool(
        latest
        and latest.status == "processing"
        and metrics_age_s is not None
        and metrics_age_s <= settings.vision_metrics_stale_s
    )
    inference_fps = latest.inference_fps if latest else None
    end_to_end_ms = latest.last_end_to_end_ms if latest else None
    calibrated = (
        settings.enable_ray_plane_geolocation
        and settings.camera_fx_px > 0
        and settings.camera_fy_px > 0
    )
    checks = [
        {
            "id": "video_continuity",
            "passed": processing,
            "evidence": "fresh vision processing"
            if processing
            else "no healthy current video stream",
            "metrics_age_s": metrics_age_s,
            "maximum_age_s": settings.vision_metrics_stale_s,
        },
        {
            "id": "inference_fps",
            "passed": inference_fps is not None
            and inference_fps >= settings.field_min_inference_fps,
            "actual": inference_fps,
            "target": settings.field_min_inference_fps,
        },
        {
            "id": "end_to_end_latency_ms",
            "passed": end_to_end_ms is not None
            and end_to_end_ms <= settings.field_max_end_to_end_ms,
            "actual": end_to_end_ms,
            "target": settings.field_max_end_to_end_ms,
        },
        {
            "id": "released_model_integrity",
            "passed": bool(latest and latest.model_integrity_verified),
            "evidence": latest.model_release if latest else "no vision metrics",
        },
        {
            "id": "telemetry",
            "passed": state.telemetry is not None,
            "evidence": "fresh MAVLink telemetry"
            if state.telemetry
            else "awaiting flight-controller telemetry",
        },
        {
            "id": "calibrated_geolocation",
            "passed": calibrated,
            "evidence": "ray-plane camera calibration enabled"
            if calibrated
            else "camera intrinsics/calibration incomplete",
        },
        {
            "id": "storage",
            "passed": persistence.available,
            "evidence": "PostGIS connected"
            if persistence.available
            else "PostGIS unavailable",
        },
        {
            "id": "transport",
            "passed": mqtt.connected,
            "evidence": "MQTT connected" if mqtt.connected else "MQTT unavailable",
        },
    ]
    return {
        "status": "field_ready"
        if all(check["passed"] for check in checks)
        else "not_field_ready",
        "automatic_authorization": False,
        "requirements": {
            "min_inference_fps": settings.field_min_inference_fps,
            "max_end_to_end_latency_ms": settings.field_max_end_to_end_ms,
        },
        "checks": checks,
        "note": "Passing runtime checks does not replace authorised field trials, security review, or operational approval.",
    }


@app.get("/api/capabilities")
async def capabilities():
    latest_vision = max(
        state.vision_metrics.values(), key=lambda item: item.timestamp, default=None
    )
    vision_status = latest_vision.status if latest_vision else "not_started"
    person_verifier_state = (
        "ready"
        if latest_vision and latest_vision.person_verifier_loaded
        else "configured"
        if settings.enable_person_verifier
        else "disabled"
    )
    fall_pose_state = (
        "ready"
        if latest_vision and latest_vision.fall_pose_model_loaded
        else "configured"
        if settings.enable_fall_detection
        else "disabled"
    )
    face_state = (
        "ready"
        if latest_vision and latest_vision.face_detector_loaded
        else "configured"
        if settings.enable_face_detection
        else "disabled"
    )
    advisory_enabled = bool(llm_worker and llm_worker.enabled)
    security_advisory_enabled = bool(
        security_advisory_worker and security_advisory_worker.enabled
    )
    return {
        "map": {
            "tile_url_template": settings.map_tile_url_template,
            "attribution": settings.map_tile_attribution,
            "offline_fallback": "local tactical grid",
            "street_view_url_template": settings.street_view_url_template,
            "street_view_mode": "external operator-requested view",
        },
        "layers": [
            "ingest",
            "perception",
            "fusion",
            "behavior_rules",
            "rules",
            "storage",
            "transport",
            "security_integrity",
            "advisory_review_optional",
        ],
        "object_tracking": "YOLO11 + ByteTrack",
        "face_detection": settings.enable_face_detection,
        "face_identification": False,
        "range_sensor": True,
        "v2x": settings.enable_v2x,
        "v2x_devices": state.v2x_device_snapshot(),
        "behavior_analytics": settings.enable_behavior_analytics,
        "llm_verification": advisory_enabled,
        "llm_mode": "advisory object-crop review only",
        "geolocation": "flat-ground approximation; camera calibration required",
        # This is intentionally operational metadata, not a control surface.
        # It allows an operator to see which isolated layers are live without
        # coupling perception to telemetry, V2X, or an advisory provider.
        "layer_status": [
            {
                "id": "video",
                "component": "OpenCV latest-frame capture",
                "state": vision_status,
                "requires": "reachable configured camera/video source",
            },
            {
                "id": "detection",
                "component": "YOLO11 GPU inference",
                "state": vision_status,
                "classes": ["person", "vessel", "vehicle"],
                "optional_custom_class": "container requires a validated port model",
            },
            {
                "id": "tracking",
                "component": "ByteTrack persistent anonymous IDs",
                "state": vision_status,
                "requires": "confirmed YOLO detections",
                "precision_gate": {
                    "minimum_observations": settings.min_track_confirmation_frames,
                    "evidence_window": settings.track_evidence_window,
                    "minimum_class_stability": settings.track_min_class_stability,
                    "person_min_mean_confidence": settings.person_track_min_mean_confidence,
                    "object_min_mean_confidence": settings.object_track_min_mean_confidence,
                },
            },
            {
                "id": "person_crosscheck",
                "component": "local independent COCO person verifier",
                "state": person_verifier_state,
                "scope": "marginal person boxes only; vetoes contradicted claims; no identity processing",
            },
            {
                "id": "fall_detection",
                "component": "local YOLO11 pose vectors + temporal fall observation",
                "state": fall_pose_state,
                "scope": "anonymous skeleton geometry only; deterministic operator-review event; no body identity",
                "model_loaded": bool(
                    latest_vision and latest_vision.fall_pose_model_loaded
                ),
                "observations": latest_vision.fall_observations if latest_vision else 0,
            },
            {
                "id": "face_observation",
                "component": "local face detection, quality, blur, anonymous track link",
                "state": face_state,
                "model_loaded": bool(
                    latest_vision and latest_vision.face_detector_loaded
                ),
                "identity_matching": "not supported",
            },
            {
                "id": "telemetry",
                "component": "MAVLink GPS + IMU + LiDAR adapter",
                "state": "receiving" if state.telemetry else "awaiting telemetry",
                "requires": "telemetry profile and a flight-controller heartbeat",
            },
            {
                "id": "geolocation",
                "component": "timestamped pose/range fusion",
                "state": "ready",
                "requires": "fresh telemetry; camera calibration for ray-plane mode",
            },
            {
                "id": "geofence_risk",
                "component": "deterministic geofence, risk, and behaviour rules",
                "state": "active",
                "geofence_count": len(state.geofences),
            },
            {
                "id": "storage",
                "component": "PostGIS track/event persistence",
                "state": "connected" if persistence.available else "unavailable",
            },
            {
                "id": "v2x",
                "component": "signed MQTT V2X event relay",
                "state": "enabled" if settings.enable_v2x else "disabled",
                "connected_devices": len(
                    [
                        device
                        for device in state.v2x_device_snapshot()
                        if device["link_status"] != "offline"
                    ]
                ),
                "requires": "V2X profile, unique source ID, and authenticated transport",
            },
            {
                "id": "security_integrity",
                "component": "telemetry and V2X replay/integrity monitor",
                "state": "enabled" if settings.enable_security_monitor else "disabled",
                "authority": "advisory findings only; never controls vehicles or peers",
            },
            {
                "id": "llm_advisory",
                "component": "optional external object/scene review",
                "state": "enabled" if advisory_enabled else "disabled",
                "authority": "advisory only; never controls detection, tracking, or alerts",
            },
            {
                "id": "security_llm_advisory",
                "component": "optional sanitised text-only security summary",
                "state": "enabled" if security_advisory_enabled else "disabled",
                "requires": "separate external text-egress approval",
                "authority": "advisory only; never controls vehicles, peers, or alerts",
            },
        ],
    }


@app.get("/api/snapshot")
async def snapshot():
    return state.snapshot()


@app.get("/api/ui/bootstrap")
async def ui_bootstrap():
    """Return one internally consistent bundle for the operations console."""
    return {
        "schema": "sentinel-console-bootstrap/1",
        "health": await health(),
        "readiness": await readiness(),
        "capabilities": await capabilities(),
        "v2x": await v2x_devices(),
        "snapshot": state.snapshot(),
    }


@app.get("/api/operator/config")
async def operator_config():
    """Return operator-editable endpoints, never credentials or device control."""
    try:
        source = CAMERA_SOURCE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        source = ""
    return {
        "camera_source": source,
        "assets": _registered_assets(),
        "camera_hot_reload": True,
        "note": "Registered assets remain inactive until their adapter or V2X peer authenticates.",
    }


@app.put("/api/operator/camera-source")
async def update_operator_camera_source(change: CameraSourceUpdate):
    source = _normalise_http_endpoint(change.source, primary_camera=True)
    _atomic_write(CAMERA_SOURCE_FILE, f"{source}\n")
    return {
        "source": source,
        "hot_reload": True,
        "message": "Primary camera source updated; the MJPEG bridge will reconnect automatically.",
    }


@app.post("/api/operator/assets")
async def register_operator_asset(registration: DeviceEndpointRegistration):
    endpoint = _normalise_http_endpoint(registration.endpoint)
    asset = {
        "device_id": registration.device_id,
        "device_type": registration.device_type,
        "endpoint": endpoint,
        "status": "registered",
    }
    assets = [item for item in _registered_assets() if item.get("device_id") != asset["device_id"]]
    assets.append(asset)
    _atomic_write(DEVICE_REGISTRY_FILE, json.dumps({"assets": assets}, indent=2) + "\n")
    return {
        "asset": asset,
        "message": "Asset registered. It remains inactive until a camera adapter or authenticated V2X peer is provisioned.",
    }


@app.get("/api/security/health")
async def security_health():
    return {
        "monitor": security_monitor.health(),
        "llm_adviser": security_advisory_worker.health()
        if security_advisory_worker
        else {"enabled": False},
        "findings": len(state.security_findings),
        "advisories": len(state.security_advisories),
        "automatic_actions": False,
    }


@app.post("/api/telemetry")
async def ingest_telemetry(telemetry: Telemetry):
    state.record_telemetry(telemetry)
    if settings.enable_security_monitor:
        for finding in security_monitor.observe_telemetry(telemetry):
            await on_security_finding(finding)
    payload = telemetry.model_dump()
    require_pipeline().queue_transport("drone/pose", payload)
    await state.broadcast("telemetry", payload)
    return {"accepted": True}


@app.post("/api/range")
async def ingest_range(measurement: RangeMeasurement):
    state.record_range(measurement)
    payload = measurement.model_dump()
    require_pipeline().queue_transport("drone/range", payload)
    await state.broadcast("range", payload)
    return {"accepted": True}


@app.post("/api/detections", status_code=202)
async def ingest_detections(batch: DetectionBatch):
    result = require_pipeline().submit(batch)
    if result == "full":
        raise HTTPException(
            503,
            "Ingress queue full; slow the vision source or increase PIPELINE_QUEUE_SIZE",
        )
    return JSONResponse(
        status_code=202,
        content={
            "accepted": 0 if result == "duplicate" else len(batch.detections),
            "queued": result == "accepted",
            "duplicate": result == "duplicate",
            "batch_id": batch.batch_id,
        },
    )


@app.post("/api/vision/metrics")
async def ingest_vision_metrics(vision_metrics: VisionMetrics):
    expired_tracks = state.record_vision_metrics(vision_metrics)
    metrics.record_vision(vision_metrics)
    for track_id in expired_tracks:
        await state.broadcast(
            "track_expired", {"track_id": track_id, "source": metrics.source}
        )
    payload = vision_metrics.model_dump()
    require_pipeline().queue_transport("ground/vision/metrics", payload)
    await state.broadcast("vision_metrics", payload)
    return {"accepted": True}


@app.post("/api/vision/preview")
async def ingest_vision_preview(preview: VisionPreview):
    try:
        image = base64.b64decode(preview.jpeg_base64, validate=True)
    except ValueError:
        raise HTTPException(422, "Preview is not valid base64 JPEG data")
    if not image or len(image) > 1_500_000:
        raise HTTPException(413, "Preview exceeds the 1.5 MB monitoring limit")
    state.record_vision_preview(preview.source, preview.timestamp, image)
    return {"accepted": True}


@app.get("/api/vision/preview.jpg", include_in_schema=False)
async def latest_vision_preview():
    preview = state.vision_preview
    if preview is None:
        raise HTTPException(404, "No annotated preview has arrived yet")
    return Response(
        content=preview["image"],
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-Preview-Source": preview["source"],
            "X-Preview-Timestamp": str(preview["timestamp"]),
        },
    )


@app.post("/api/geofences")
async def upsert_geofence(geofence: Geofence, request: Request):
    geofence = geofence.model_copy(update={"version": geofence_version(geofence)})
    await record_audit(
        request.state.principal,
        "geofence_upsert",
        f"geofence:{geofence.id}",
        "Operator changed a deterministic geofence definition",
        {"restricted": geofence.restricted, "vertex_count": len(geofence.coordinates)},
    )
    state.geofences = [
        existing for existing in state.geofences if existing.id != geofence.id
    ] + [geofence]
    payload = geofence.model_dump()
    await state.broadcast("geofence", payload)
    return payload


@app.get("/api/missions")
async def list_missions():
    try:
        missions = await asyncio.to_thread(persistence.list_missions)
    except ConnectionError:
        raise HTTPException(503, "Mission store is unavailable")
    state.missions = {mission.id: mission for mission in missions}
    return {"missions": [mission.model_dump(mode="json") for mission in missions]}


@app.get("/api/missions/{mission_id}")
async def get_mission(mission_id: str):
    try:
        mission = await asyncio.to_thread(persistence.get_mission, mission_id)
    except KeyError:
        raise HTTPException(404, "Mission not found")
    except ConnectionError:
        raise HTTPException(503, "Mission store is unavailable")
    state.missions[mission.id] = mission
    return mission


@app.post("/api/missions")
async def save_mission(change: MissionChange, request: Request):
    validation = validate_mission(change.mission, state.geofences)
    try:
        current = await asyncio.to_thread(persistence.get_mission, change.mission.id)
    except KeyError:
        current = None
    except ConnectionError:
        raise HTTPException(503, "Mission store is unavailable")
    if current is None and change.expected_version is not None:
        raise HTTPException(409, "Mission does not exist at the expected version")
    if current is not None and change.expected_version != current.version:
        raise HTTPException(409, "Mission version conflict; reload before saving")
    now = time.time()
    mission = MissionRecord(
        **change.mission.model_dump(),
        version=1 if current is None else current.version + 1,
        state=validation.state,
        created_at=now if current is None else current.created_at,
        updated_at=now,
        updated_by=request.state.principal.subject,
    )
    await record_audit(
        request.state.principal,
        "mission_created" if current is None else "mission_updated",
        f"mission:{mission.id}",
        change.justification,
        {
            "version": mission.version,
            "state": mission.state,
            "vehicle_id": mission.vehicle_id,
            "waypoint_count": validation.statistics.waypoint_count,
            "validation_errors": len(
                [issue for issue in validation.issues if issue.severity == "error"]
            ),
        },
    )
    try:
        await asyncio.to_thread(persistence.save_mission, mission)
    except RuntimeError:
        raise HTTPException(409, "Mission version conflict; reload before saving")
    state.missions[mission.id] = mission
    payload = {
        "mission": mission.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
    }
    await state.broadcast("mission", payload)
    return payload


@app.get("/api/missions/{mission_id}/validation")
async def validate_saved_mission(mission_id: str):
    try:
        mission = await asyncio.to_thread(persistence.get_mission, mission_id)
    except KeyError:
        raise HTTPException(404, "Mission not found")
    result = validate_mission(mission, state.geofences)
    return result


@app.post("/api/missions/{mission_id}/prepare-upload")
async def prepare_mission_upload(
    mission_id: str, preparation: MissionPrepareUpload, request: Request
):
    try:
        current = await asyncio.to_thread(persistence.get_mission, mission_id)
    except KeyError:
        raise HTTPException(404, "Mission not found")
    if current.version != preparation.expected_version:
        raise HTTPException(409, "Mission version conflict; reload before preparing")
    validation = validate_mission(current, state.geofences)
    if not validation.valid:
        raise HTTPException(409, "Mission validation failed")
    telemetry = state.telemetry_by_vehicle.get(current.vehicle_id)
    telemetry_age = time.time() - telemetry.timestamp if telemetry else float("inf")
    if telemetry is None or telemetry_age > settings.telemetry_max_skew_s:
        raise HTTPException(409, "Fresh vehicle telemetry is required")
    if telemetry.vehicle_id is None:
        raise HTTPException(409, "Telemetry does not identify a vehicle")
    if telemetry.vehicle_id != current.vehicle_id:
        raise HTTPException(409, "Selected mission vehicle does not match telemetry vehicle")
    prepared = current.model_copy(
        update={
            "version": current.version + 1,
            "state": "READY_TO_UPLOAD",
            "updated_at": time.time(),
            "updated_by": request.state.principal.subject,
        }
    )
    await record_audit(
        request.state.principal,
        "mission_prepared_for_upload",
        f"mission:{mission_id}",
        preparation.justification,
        {"version": prepared.version, "vehicle_id": prepared.vehicle_id},
    )
    try:
        await asyncio.to_thread(persistence.save_mission, prepared)
    except RuntimeError:
        raise HTTPException(409, "Mission version conflict; reload before preparing")
    state.missions[prepared.id] = prepared
    await state.broadcast("mission", prepared.model_dump(mode="json"))
    return {
        "mission": prepared,
        "hardware_upload_available": False,
        "blocking_dependency": "EXTERNAL_HARDWARE",
        "message": "Mission is validated but no vehicle command adapter is enabled.",
    }


@app.delete("/api/missions/{mission_id}")
async def delete_mission(
    mission_id: str, deletion: MissionDelete, request: Request
):
    await record_audit(
        request.state.principal,
        "mission_deleted",
        f"mission:{mission_id}",
        deletion.justification,
        {"expected_version": deletion.expected_version},
    )
    try:
        await asyncio.to_thread(
            persistence.delete_mission, mission_id, deletion.expected_version
        )
    except RuntimeError:
        raise HTTPException(409, "Mission version conflict or mission not found")
    state.missions.pop(mission_id, None)
    await state.broadcast("mission_deleted", {"mission_id": mission_id})
    return {"deleted": True, "mission_id": mission_id}


@app.post("/api/v2x/events")
async def ingest_v2x_event(envelope: V2XEnvelope):
    if not settings.enable_v2x:
        raise HTTPException(401, "Unauthenticated, expired, or disabled V2X message")
    validation = v2x_validation_reason(
        envelope, settings.v2x_shared_secret, settings.v2x_max_age_s
    )
    if validation != "accepted":
        finding = security_monitor.rejected_v2x(envelope.source_id, validation)
        if finding:
            await on_security_finding(finding)
        raise HTTPException(401, "Unauthenticated, expired, or disabled V2X message")
    if (
        envelope.source_id != settings.v2x_source_id
        and envelope.source_id not in settings.allowed_v2x_sources
    ):
        finding = security_monitor.rejected_v2x(envelope.source_id, "unauthorized_peer")
        if finding:
            await on_security_finding(finding)
        raise HTTPException(401, "Unauthenticated, expired, or disabled V2X message")
    if not require_pipeline().claim_v2x_message(envelope.message_id):
        raise HTTPException(409, "Repeated V2X message ID rejected")
    replay = (
        security_monitor.observe_v2x(envelope)
        if settings.enable_security_monitor
        else None
    )
    if replay:
        await on_security_finding(replay)
        raise HTTPException(409, "Repeated V2X message ID rejected")
    if envelope.source_id == settings.v2x_source_id:
        return {"accepted": False, "reason": "local message ignored"}
    remote_event = envelope.event.model_copy(update={"origin": envelope.source_id})
    await require_pipeline().dispatch_event(remote_event, relay_v2x=False)
    return {"accepted": True, "message_id": envelope.message_id}


@app.post("/api/v2x/heartbeats")
async def ingest_v2x_heartbeat(heartbeat: V2XHeartbeat):
    if not settings.enable_v2x:
        raise HTTPException(401, "Unauthenticated, expired, or disabled V2X heartbeat")
    validation = v2x_heartbeat_validation_reason(
        heartbeat, settings.v2x_shared_secret, settings.v2x_max_age_s
    )
    if validation != "accepted":
        finding = security_monitor.rejected_v2x(heartbeat.device_id, validation)
        if finding:
            await on_security_finding(finding)
        raise HTTPException(401, "Unauthenticated, expired, or disabled V2X heartbeat")
    if (
        heartbeat.device_id != settings.v2x_source_id
        and heartbeat.device_id not in settings.allowed_v2x_sources
    ):
        finding = security_monitor.rejected_v2x(
            heartbeat.device_id, "unauthorized_peer"
        )
        if finding:
            await on_security_finding(finding)
        raise HTTPException(401, "Unauthenticated, expired, or disabled V2X heartbeat")
    status = state.record_v2x_heartbeat(heartbeat)
    if status is None:
        finding = security_monitor.rejected_v2x(heartbeat.device_id, "replay")
        if finding:
            await on_security_finding(finding)
        raise HTTPException(409, "Repeated or regressed V2X heartbeat sequence")
    payload = status.model_dump(mode="json")
    await state.broadcast("v2x_device", payload)
    return {"accepted": True, "device": payload}


@app.get("/api/v2x/devices")
async def v2x_devices():
    devices = state.v2x_device_snapshot()
    return {
        "enabled": settings.enable_v2x,
        "tls_configured": settings.mqtt_tls_enabled,
        "online": len(
            [device for device in devices if device["link_status"] != "offline"]
        ),
        "devices": devices,
    }


@app.post("/api/evidence/verifications")
async def ingest_evidence_verification(
    verification: EvidenceVerification, request: Request
):
    evidence_request = next(
        (
            item
            for item in state.evidence_requests
            if item.request_id == verification.request_id
        ),
        None,
    )
    if evidence_request is None:
        raise HTTPException(404, "Unknown or expired evidence request")
    if not await on_evidence_verification(verification):
        raise HTTPException(410, "Evidence request has expired")
    await record_audit(
        request.state.principal,
        "advisory_evidence_recorded",
        f"event:{verification.event_id}",
        "Advisory-only external review was attached to an existing evidence request",
        {
            "provider": verification.provider[:96],
            "verdict": verification.verdict,
            "request_id": verification.request_id,
        },
    )
    return {"accepted": True, "advisory_only": True}


@app.post("/api/events/{event_id}/acknowledge")
async def acknowledge_event(
    event_id: str, acknowledgement: Acknowledge, request: Request
):
    if not acknowledgement.acknowledged:
        raise HTTPException(422, "Acknowledgement cannot revert event lifecycle state")
    for event in state.events:
        if event.id == event_id:
            if event.state == "ACKNOWLEDGED":
                return event
            if not event_transition_allowed(event.state, "ACKNOWLEDGED"):
                raise HTTPException(
                    409, f"Event cannot transition from {event.state} to ACKNOWLEDGED"
                )
            await record_audit(
                request.state.principal,
                "event_acknowledged",
                f"event:{event_id}",
                acknowledgement.justification,
                {
                    "acknowledged": acknowledgement.acknowledged,
                    "severity": event.severity,
                },
            )
            event.acknowledged = acknowledgement.acknowledged
            event.state = "ACKNOWLEDGED"
            reviewed_at = time.time()
            event.provenance.operator_reviewed = acknowledgement.acknowledged
            event.provenance.reviewed_by = request.state.principal.subject
            event.provenance.reviewed_at = reviewed_at
            await asyncio.to_thread(persistence.save_event, event)
            await asyncio.to_thread(
                persistence.review_event,
                event.id,
                acknowledged=acknowledgement.acknowledged,
                reviewer=request.state.principal.subject,
                reviewed_at=reviewed_at,
            )
            await state.broadcast("event", event.model_dump(mode="json"))
            return event
    raise HTTPException(404, "Event not found")


@app.post("/api/events/{event_id}/transition")
async def transition_event(
    event_id: str, transition: EventTransition, request: Request
):
    event = next((item for item in state.events if item.id == event_id), None)
    if event is None:
        raise HTTPException(404, "Event not found")
    if not event_transition_allowed(event.state, transition.state):
        raise HTTPException(
            409, f"Event cannot transition from {event.state} to {transition.state}"
        )
    reviewed_at = time.time()
    await record_audit(
        request.state.principal,
        "event_state_transition",
        f"event:{event_id}",
        transition.justification,
        {
            "from": event.state,
            "to": transition.state,
            "severity": event.severity,
        },
    )
    try:
        await asyncio.to_thread(
            persistence.transition_event,
            event_id,
            state=transition.state,
            reviewer=request.state.principal.subject,
            reviewed_at=reviewed_at,
        )
    except KeyError:
        raise HTTPException(404, "Event persistence record not found")
    event.state = transition.state
    if transition.state == "ACKNOWLEDGED":
        event.acknowledged = True
    event.provenance.operator_reviewed = True
    event.provenance.reviewed_by = request.state.principal.subject
    event.provenance.reviewed_at = reviewed_at
    payload = event.model_dump(mode="json")
    await state.broadcast("event", payload)
    return payload


@app.post("/api/evidence/{evidence_id}/legal-hold")
async def update_evidence_legal_hold(
    evidence_id: str, update: LegalHoldUpdate, request: Request
):
    await record_audit(
        request.state.principal,
        "evidence_legal_hold_updated",
        f"evidence:{evidence_id}",
        update.justification,
        {"legal_hold": update.legal_hold},
    )
    try:
        return await asyncio.to_thread(
            persistence.set_evidence_legal_hold,
            evidence_id,
            legal_hold=update.legal_hold,
            actor=request.state.principal.subject,
            justification=update.justification,
        )
    except KeyError:
        raise HTTPException(404, "Evidence record not found or already purged")


@app.get("/api/evidence/{evidence_id}/verify")
async def verify_evidence(evidence_id: str):
    try:
        record = await asyncio.to_thread(persistence.get_evidence, evidence_id)
    except KeyError:
        raise HTTPException(404, "Evidence record not found")
    if record["purged"]:
        return {"evidence_id": evidence_id, "valid": False, "purged": True}
    key = await asyncio.to_thread(
        load_evidence_key, settings.evidence_encryption_key_file
    )
    result = await asyncio.to_thread(
        verify_evidence_files,
        record["artifact_path"],
        record["manifest_path"],
        key,
    )
    result["database_hash_valid"] = (
        result.get("artifact_sha256") == record["artifact_sha256"]
    )
    result["valid"] = bool(result.get("valid") and result["database_hash_valid"])
    result["legal_hold"] = record["legal_hold"]
    return result


@app.get("/api/audit/verify")
async def verify_audit_log(request: Request):
    result = await asyncio.to_thread(persistence.verify_audit_chain)
    await record_audit(
        request.state.principal,
        "audit_chain_verified",
        "audit-log",
        "System administrator requested an integrity check",
        {"valid": result["valid"]},
    )
    return result


@app.websocket("/ws/operations")
async def operations_socket(websocket: WebSocket):
    await websocket.accept()
    if len(state.clients) >= settings.websocket_max_clients:
        await websocket.close(code=4429, reason="Connection capacity reached")
        return
    try:
        authentication = await asyncio.wait_for(websocket.receive_json(), timeout=5)
    except (TimeoutError, ValueError):
        await websocket.close(code=4401, reason="Authentication message required")
        return
    if (
        not isinstance(authentication, dict)
        or authentication.get("type") != "authenticate"
    ):
        await websocket.close(code=4401, reason="Authentication message required")
        return
    if settings.auth_enabled:
        try:
            principal = auth_manager.decode_token(
                str(authentication.get("access_token", ""))
            )
        except AuthenticationError:
            await websocket.close(code=4401, reason="Authentication required")
            return
        if not principal.permits(VIEWER_ROLES):
            await websocket.close(code=4403, reason="Insufficient role")
            return
    state.clients.add(websocket)
    await websocket.send_json(
        {
            "type": "session",
            "data": {
                "authenticated": True,
                "subject": principal.subject if settings.auth_enabled else "development",
            },
        }
    )
    await websocket.send_json({"type": "snapshot", "data": state.snapshot()})
    try:
        while True:
            message = await websocket.receive_text()
            if message != "keepalive":
                await websocket.close(code=4400, reason="Unsupported client message")
                break
    except WebSocketDisconnect:
        LOGGER.debug("Operations WebSocket disconnected")
    finally:
        state.clients.discard(websocket)


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/styles.css", include_in_schema=False)
async def styles():
    return FileResponse(WEB_ROOT / "styles.css", media_type="text/css")


@app.get("/operations.css", include_in_schema=False)
async def operations_styles():
    return FileResponse(WEB_ROOT / "operations.css", media_type="text/css")


@app.get("/app.js", include_in_schema=False)
async def javascript():
    return FileResponse(WEB_ROOT / "app.js", media_type="application/javascript")
