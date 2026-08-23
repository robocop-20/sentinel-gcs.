# Sentinel master assurance status

Status date: 2026-08-22  
Release level: `DEVELOPMENT`

This matrix records evidence, not intent. `VERIFIED` means an executable check
was run against the current source in this session. Historical project notes
are not promoted to current verification without a repeatable run.

| Subsystem | Status | Implementation | Test/evidence | Precision/latency | Failure and security behavior | Remaining gap |
| --- | --- | --- | --- | --- | --- | --- |
| Dynamic camera source | VERIFIED | `config/camera-source.txt`, PowerShell normalizer/setter, watched host bridge source | IP/port/URL normalization and atomic hot-reload smoke passed; baseline report | No video latency claim | Validates scheme/port; stable Docker adapter; invalid updates fail closed | Live camera switch and reconnect timing require controlled bench evidence |
| MJPEG host bridge | PARTIAL | JPEG SOI/EOI reframing, authenticated endpoint, health/readiness, exclusive listener | Syntax and focused frame/source tests exist; current full suite unavailable | Not benchmarked | Token protected; upstream errors do not crash API; closes malformed stream | Corrupted/frozen/live camera fault matrix not yet executed |
| OpenCV capture | PARTIAL | Latest-frame capture and exponential reconnect in `vision_runtime.py`/`vision_worker.py` | Source compiles; historical tests exist | No current FPS/path latency | Drops stale frames and isolates API posting | Requires recorded replay and live camera benchmark |
| YOLO11 detection | UNVERIFIED | Ultralytics adapter, latest-frame inference, class-specific candidate/publication policy, GPU/CPU configuration and model release manifest | Source compiles; contract/release tests and exact-weight benchmark path exist | No current precision/recall/AP/FPS | Model failure is surfaced through vision metrics/failsafe; stale frames are dropped | Requires executable vision environment and representative labelled replay; port class additionally needs dataset |
| Port/container model | BLOCKED_DATASET | Training, validation, promotion and rollback scaffolding | Dataset validator/release-gate tests exist | No port metrics may be claimed | Promotion requires manifest/hash and gate | Authorised labelled train/validation/test dataset |
| Temporal confirmation | TESTED | Per-class candidate/confirmation gate, rolling confidence and class stability | Source compiles; focused pure contract checks and unit tests exist | Not measured against labelled replay | Prevents weak candidates reaching rules/evidence | `EXTERNAL_DATASET`: measure false-alarm reduction, delay and missed events |
| ByteTrack anonymous tracking | UNVERIFIED | Conservative two-threshold ByteTrack configuration, bounded publication and NEW/ACTIVE/OCCLUDED/TEMPORARILY_LOST/REACQUIRED lifecycle | Source compiles; lifecycle/config tests exist | IDF1/HOTA/ID switches not measured | Anonymous IDs only; no biometric continuity | `EXTERNAL_DATASET`: recorded occlusion/re-entry corpus; executable GPU replay benchmark |
| Motion/history | PARTIAL | Bounded image-plane motion estimator and track history | Unit tests exist | Not benchmarked | Missing observations degrade to unavailable values | Validate scale, jitter and history bounds under replay |
| Fall observation | PARTIAL | YOLO pose vectors plus temporal confirmation/cooldown | Unit tests exist; model present in workspace | No sensitivity/specificity claim | Advisory `Possible fall`; no medical diagnosis/action | Labelled fall/non-fall replay and recovery-state validation |
| Anonymous face observation | PARTIAL | Local YuNet box, landmarks, quality, blur and short-lived association | Unit tests exist | No detection quality benchmark | No names, embeddings, gallery or cross-session identity | Representative privacy/quality evaluation and live runtime evidence |
| MAVLink telemetry | BLOCKED_HARDWARE | Heartbeat, position, attitude, battery, link and distance ingestion | Parser/service tests exist | Packet loss/jitter/reconnect unmeasured | Stale telemetry must not geolocate or imply LIVE | Multi-vehicle abstraction, mission protocol depth and HIL flight controller |
| GPS/IMU/LiDAR quality | PARTIAL | Timestamped telemetry/range schemas, GPS fix taxonomy and freshness gates | Source compiles; schema/geolocation tests exist | No sensor-quality measurements | Missing LiDAR is nullable, not zero; stale association rejected | `EXTERNAL_HARDWARE`: calibrated device and packet-quality evidence |
| Geolocation | BLOCKED_HARDWARE | Approximate and calibrated ray-plane paths, distortion correction, telemetry skew gate, camera-bound checked intrinsic/extrinsic profile loaders and calibration scripts | Source compiles; calibration/geolocation unit tests exist | No real error budget/RMSE | Marks uncertainty/mode; refuses mismatched calibration/aspect and stale telemetry | `EXTERNAL_HARDWARE`/`EXTERNAL_FIELD_TEST`: calibrate actual camera and validate known targets |
| Geofencing/risk | PARTIAL | Polygon containment, version hash, entry/exit, loiter/proximity/quiet-hours rules | Unit tests exist | Rule execution not benchmarked | Deterministic explainable factors; LLM isolated | Complete zone lifecycle/circular zones and runtime integration evidence |
| Mission planning | PARTIAL | Versioned mission schema/persistence, geofence/route validation, optimistic edit checks, import/export and prepare-only adapter boundary | Source compiles; mission validation tests exist | Validation latency not benchmarked | No automatic upload/control; role, freshness and audit gates apply; restricted crossing rejected | Execute API/database/E2E workflow and HIL command-protocol adapter before operational use |
| Event/alert lifecycle | PARTIAL | Event creation, durable deduplication, explicit NEW/ACKNOWLEDGED/UNDER_REVIEW/RESOLVED/DISMISSED transitions and justification/audit fields | Source compiles; event/provenance tests exist | Event-to-alert metric exists, not currently measured | LLM has no transition authority; state mutation is server validated | Execute authorization/audit/anti-flood integration and latency evidence |
| PostGIS persistence | PARTIAL | Separate pools, indexed tracks/events/evidence/audit tables | Historical isolated validation documented | No current query-plan/latency evidence | Durable queue protects temporary outage | Migration framework, spatial schema/index review and repeat runtime test |
| Evidence custody | PARTIAL | AES-256-GCM artifacts, SHA-256, HMAC manifests, legal hold/retention | Historical corruption/hold tests documented | Creation/verify latency unmeasured | Fail-closed verification; keys external to artifacts | Repeat corruption matrix and storage-full fault test |
| Audit chain | PARTIAL | Append-only SHA-256 chained records and verification API | Historical tests documented | Not applicable | Detects record hash/chain mismatch | Extend audited action coverage and execute modify/delete/insert/reorder matrix |
| MQTT/outbox | PARTIAL | QoS 2 critical delivery, durable SQLite WAL outbox, bounded retry/circuit/dead letter | Historical broker outage validation documented | Current delivery latency not measured | Optional outage does not stop local pipeline | Repeat failure/recovery and retry-storm tests |
| Signed V2X | BLOCKED_FIELD_TEST | Signed/versioned envelopes, expiry/replay/duplicate checks, source allowlist, heartbeat and simulator agent | Source compiles; validation tests exist | No field latency/reliability | Rejects malformed, unauthorized, expired, replayed and invalid signatures | Provision per-peer credentials/certificates; run broker/peer field transport matrix |
| LLM advisory | BLOCKED_CREDENTIAL | Common Gemini/OpenRouter/xAI adapter, schema validation, timeout/retry/circuit and encrypted crop access | Unit tests exist | No provider latency/cost/rate evidence | Advisory only; no identity, control, risk or alert authority | Current credentials/provider availability and approved egress test |
| Authentication/RBAC | PARTIAL | Argon2id users, short JWTs, service tokens and route permissions | Historical isolated validation documented | Login latency unmeasured | Rate limits, strict schemas, mTLS boundary | Required role set and current negative authorization matrix need completion |
| TLS/mTLS | PARTIAL | TLS 1.3 gateway, service and broker/database client identities | Historical isolated validation documented | Handshake latency unmeasured | Plaintext/unauthenticated paths intended to reject | Current cert expiry/rotation/revocation validation |
| Observability | PARTIAL | Structured logs, correlation/trace context, Prometheus/Grafana/Alertmanager | Historical isolated validation documented | Metrics exist; current series unavailable | Bounded labels and external metrics path blocked | Expand sensor/camera/LLM/system resource coverage and repeat scrape test |
| Backup/restore | TESTED | Checksum backup and isolated restoration scripts | Historical restore validation documented | Restore duration/RPO/RTO not current | Destructive restore requires explicit approval | Repeat on current schema/evidence metadata when Docker is accessible |
| Operations console | PARTIAL | Ten functional workspaces, mission/event workflows, map/video, freshness/reconnect and audited bounded read-only historical replay | JavaScript syntax and seven static console contract checks passed; all referenced IDs resolve | No browser performance measurements | N/A/stale/offline/replay text, role gating and bounded WebSocket/history updates; no fake default telemetry | Mandatory visual/responsive/browser performance verification is unverified because local-preview permission was declined |
| CI/supply chain | PARTIAL | Pinned requirements/base images and CI compile/lint/type/test/Bandit/audit/build gates | Compose and syntax gates passed locally | Build duration unavailable | Non-root images and read-only CI permissions | No Git metadata, lock hashes, SBOM, signature or current vulnerability results |
| Dynamic source preservation | VERIFIED | Single authoritative file retained; no `.env` phone-IP duplication found | Repository search found the active phone IP only in the authoritative file | Not applicable | Configuration change is atomic and observable | Preserve throughout all later phases |

## Current baseline constraints

- Docker Desktop was started, but this sandbox was denied access to its named
  pipe. Runtime/image claims remain unverified here.
- Outbound package installation is blocked; the accessible Python 3.14 runtime
  does not contain the pinned project/test dependencies.
- The workspace has no `.git` directory. This is a release-provenance gap, not
  permission to initialize, overwrite, or fabricate history.
- `D:\fpv` has not been modified.

## Assurance artifacts added in this pass

- Architecture, UI/human-factors, threat model, safety case, hazard log, compliance mapping, FMEA/single-point analysis, performance budget and fault-injection matrix.
- Camera intrinsic/extrinsic calibration tooling and controlled geolocation validation procedure.
- Port-model release standard, background-negative release gates and empirical confidence-calibration/ECE tooling.
- Hardware and EMI/EMC qualification plans, future cutover/rollback plan, and precision/reliability/security reports.
