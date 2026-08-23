# Sentinel hardening roadmap

This roadmap tracks the supplied H1-H7 engineering brief. It is a review gate,
not a certification statement. The target is evidence-backed operational
rigour; independent security, safety, field, legal, and procurement approvals
remain mandatory.

| Phase | Scope | Status | Review gate |
| --- | --- | --- | --- |
| H1 | Health contracts, structured logs, CI, secrets posture, reproducible non-root containers | Implemented; validation recorded below | Operator review before H2 |
| H2 | TLS/mTLS, OAuth2/JWT RBAC, tamper-evident audit, encryption | Implemented and isolated-stack validated; live cutover requires operator password bootstrap | Operator accepts local CA and rotates deployment credentials |
| H3 | MQTT resilience, idempotency, backup/restore | Implemented and isolated fault/restore validated; live cutover pending H2 bootstrap | H2 threat model accepted |
| H4 | Metrics, tracing, dashboards, alert rules | Implemented and isolated-stack validated; live cutover pending | H3 failure tests pass |
| H5 | Evidence integrity, retention, provenance | Pending | Retention authority defined |
| H6 | Operations-console redesign | Pending | Backend contracts frozen |
| H7 | Load/security/chaos validation, SBOM/signing and release runbooks | Pending | Independent acceptance evidence |

## H1 delivered

- Conventional `/healthz` liveness and `/readyz` dependency readiness for the
  API, plus an internal health server for vision, telemetry and V2X workers.
- MJPEG host adapter exposes the same liveness/readiness contract.
- JSON logs with UTC time, service, severity, correlation ID and bounded event
  metadata. Request bodies, credentials, camera URLs and pixels are excluded.
- Restricted CORS defaults and validated HTTP(S) outbound adapter URLs.
- Exact top-level Python dependency versions taken from the exercised local
  runtime; reproducible base-image and infrastructure-image digests.
- Multi-stage API/vision images running as UID/GID 10001.
- CI gates for compilation, lint, focused strict typing, unit tests, Bandit,
  dependency audit and API container build.
- Database password removed from committed Compose. The ignored local `.env`
  retains the current development password so the existing volume is not made
  inaccessible; rotate it before any field deployment.

## H2 privacy architecture decision

The supplied brief asks for RetinaFace, ArcFace and an authorised watchlist
API. The current approved architecture in `STACK_ARCHITECTURE.md` explicitly
prohibits embeddings, galleries, named-person lookup, ArcFace and biometric
identification. The deployed implementation therefore remains local OpenCV
YuNet face **observation** with anonymous short-lived association and privacy
blur. H2 does not introduce biometric identification. A future regulated
change must not add it until an authorised owner explicitly changes that
architecture and supplies legal basis, retention, access-control, bias/error
evaluation and human-review requirements.

## H2 delivered

- TLS 1.3 browser gateway; the API is no longer published directly.
- Mutual TLS for gateway-to-API and worker-to-API connections, with separate
  certificates for vision, telemetry and V2X.
- MQTT TLS 1.3 with mandatory client certificates, certificate-derived broker
  identities and topic ACLs; anonymous/plaintext access is rejected.
- PostgreSQL TLS 1.3 with client-certificate authentication mapped only from the
  API identity to the Sentinel database role; non-TLS host connections reject.
- Short-lived JWTs issued from OAuth2 password and client-credentials flows.
  Argon2id hashes back the Viewer, Operator, Analyst, Auditor, Administrator,
  System-Admin and internal Service role model. There is no biometric/watchlist API
  under the approved anonymous-face architecture.
- Strict request schemas, bounded bodies, endpoint rate limits, authenticated
  WebSockets and authenticated preview retrieval.
- Append-only PostgreSQL audit records chained with SHA-256 for authentication,
  geofence changes, event acknowledgements, advisory evidence and verification.
- AES-256-GCM object-evidence envelopes with per-record nonces. The worker never
  writes a plaintext crop when evidence capture is enabled; advisory decryption
  occurs only in memory.

## H2 validation record

- 59 non-GPU tests passed; new security modules pass strict mypy and Ruff.
- Isolated Compose trial: gateway, API, MQTT and PostGIS all healthy.
- HTTPS returned HSTS; missing JWT was rejected; operator JWT succeeded;
  unknown request fields returned 422; oversized bodies returned 413.
- Direct API and MQTT access without client certificates were rejected.
- API-to-PostgreSQL reported `ssl=true`; the audit chain reported valid.
- API process remained non-root at UID/GID 10001.

## H3 delivered

- Disk-backed SQLite WAL outbox for MQTT and PostgreSQL delivery. Records are
  acknowledged and removed only after downstream success; the API state is on
  a dedicated persistent volume.
- MQTT QoS 2 for event, V2X event, security-finding, evidence-request and
  dead-letter topics; QoS 1 for ordinary operational state. Clients use stable
  IDs, persistent sessions and bounded reconnect backoff.
- Bounded exponential delivery retry, circuit breakers and an MQTT dead-letter
  topic for critical records that exhaust normal retries. Low-value track and
  telemetry updates coalesce while critical events never do.
- Restart-safe idempotency claims for detection batches, event fingerprints
  and signed V2X message IDs. The vision worker emits a stable batch UUID for
  API retry.
- Separate PostgreSQL ingestion-write and dashboard/read connection pools,
  plus time/source/severity indexes for the principal query paths.
- Exponential OpenCV stream reconnect with a bounded ceiling and visible
  reconnect state; successful frames reset the backoff.
- Checksum-producing backup, non-destructive isolated restore-test and explicit
  approved destructive-restore scripts. Recovery targets and procedures are in
  `DATABASE_RECOVERY.md`.

## H3 validation record

- 65 non-GPU tests passed before the fault-injection test was added; the H3
  focused suite then passed 9/9, including simulated broker failure/recovery.
- API, PostGIS and MQTT images built from pinned bases; Compose validation
  resolved successfully.
- Repeated detection batch returned `duplicate=true` without re-queueing.
- With MQTT stopped, the API stayed alive and a QoS-2 event remained in the
  durable outbox. After broker recovery and circuit cooldown the outbox drained
  to zero.
- With PostGIS stopped, the API stayed alive and a critical storage record
  remained durable. After database recovery it drained and exactly one event
  row existed.
- A custom-format backup passed SHA-256 verification and restored successfully
  into an isolated validation database; core event, track and audit tables were
  queried before the validation database was removed.

## H4 delivered and validated

- Prometheus instrumentation for API latency, inference/end-to-end latency,
  FPS, frame drops, anonymous track-ID churn, event-to-alert latency, LLM
  advisory latency, service uptime, queues, outbox age, dead letters and circuit
  state. Labels are bounded to prevent untrusted high-cardinality growth.
- W3C Trace Context and correlation IDs in structured logs. Vision detection
  batches and background fusion use the same deterministic trace identity.
- Pinned Prometheus, Alertmanager and Grafana services in an `ops` profile, with
  persistent volumes and loopback-only engineering ports.
- Prometheus scrapes the API over a dedicated mTLS client certificate. The edge
  gateway returns 404 for `/metrics`.
- A provisioned engineering dashboard and eight deterministic SLA/backpressure
  alert rules. External alert metadata egress remains off until a site approves
  and secrets a webhook receiver.
- Isolated validation confirmed the Prometheus target `up`, all eight rules
  loaded, Grafana healthy with the dashboard provisioned, Alertmanager ready,
  and the edge metrics path blocked.

## H5 delivered and validated

- Unique immutable AES-256-GCM evidence artifacts replace the previous
  one-file-per-track overwrite behavior. Every encrypted artifact has a
  SHA-256 and a canonical HMAC-SHA-256 signed manifest.
- Independent PostGIS custody records retain source/frame time, anonymous track,
  model release and weights hash, artifact hash/size, retention deadline,
  legal-hold state and purge time.
- A dedicated non-root retention service uses a separate PostgreSQL mTLS
  identity. It rejects filesystem paths outside the evidence root and exempts
  all legal-hold records.
- Local events carry model, confidence, frame-time, content-addressed geofence,
  evidence and human-review provenance. Event review persists reviewer/time and
  requires an audit justification.
- 71 non-GPU tests, Ruff, strict H1-H5 infrastructure typing and Compose
  validation passed. Isolated validation proved file/manifest/database
  integrity, legal-hold exemption, release-and-purge behavior and event review
  provenance. See `EVIDENCE_CUSTODY.md`.

## H1 validation record

- `python -m compileall -q app tests`: passed.
- Isolated full suite: 54 tests passed.
- Ruff: passed.
- Strict mypy for H1 infrastructure: passed.
- Bandit medium/high gate: passed with narrowly documented network-boundary
  exceptions.
- `pip-audit -r requirements-api.txt`: no known vulnerabilities at test time.
- API container: UID 10001, `/healthz` 200, `/readyz` 200, correlation response
  header present, JSON request log emitted.
