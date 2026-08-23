# Sentinel threat model

Method: STRIDE. Status: engineering threat model, not penetration-test or certification evidence.

## Assets and safety invariants

Protected assets are operator identity, service credentials, telemetry integrity, camera provenance, model weights, geofences, missions, events, V2X messages, evidence keys/artifacts, audit continuity, and availability. The primary invariant is that untrusted input and optional AI cannot issue vehicle commands or alter deterministic safety state.

| Surface / threat | STRIDE | Implemented control | Verification | Remaining dependency |
|---|---|---|---|---|
| Browser token theft | S/I/E | short-lived JWT, session storage, CSP, no token in WebSocket URL, TLS gateway | static token-path test; runtime auth test pending | controlled browser test |
| API spoofing/abuse | S/E/D | JWT, RBAC, strict Pydantic schemas, body/rate limits, correlation IDs | auth tests exist; not executed here | runnable test environment |
| Service impersonation | S/E | mTLS client certs plus service credentials | Compose config resolves | certificate provisioning/rotation exercise |
| PostGIS tampering | T/R | mTLS, transaction boundaries, checksummed migrations, append-only audit trigger/hash chain | unit tests exist; restore/runtime test pending | isolated database runtime |
| Camera injection/freeze | S/T/D | single authoritative source, robust JPEG reconstruction, latest-frame policy, reconnect/freshness state | parser/source tests exist | live fault injection |
| MAVLink spoof/replay | S/T | source/system/component IDs and anomaly advisory; no command adapter | schema/static review | authenticated transport hardware |
| MQTT interception | S/T/I | TLS verification, client certificates, ACL file, QoS 2 critical topics | config/static tests | live broker negative tests |
| V2X forgery/replay | S/T/R | canonical HMAC, expiry, message ID idempotency, sequence monotonicity, peer allowlist | V2X tests exist | unique peer credentials and field peers |
| LLM prompt/data attack | T/I/E | explicit image/text egress gates, bounded crop, strict structured verdict, circuit breaker, advisory-only sink | verifier tests exist | provider credentials and network test |
| Evidence replacement | T/R | AES-256-GCM, SHA-256 artifact hash, HMAC manifest, legal hold, append-only audit | integrity tests exist | recovery/custody exercise |
| Model substitution | T | manifest class check, weights SHA-256, release gate | model-release tests exist | validated port dataset/model |
| Container escape | E | pinned bases, non-root app containers, read-only root, dropped capabilities, no-new-privileges, isolated networks | Compose resolution passed | image/container scanner |
| Resource exhaustion | D | bounded queues/history/connections, latest-frame replacement, rate limits, circuit breakers | unit/static checks | soak and load test |
| Malicious update | T/E | pinned images/dependencies, release hashes planned | static inspection | signed CI release/SBOM pipeline |

## Trust decisions

- Camera, MAVLink, MQTT, V2X, browser, database rows, provider output, and files are untrusted until validated at their boundary.
- A valid signature proves knowledge of the current shared secret, not individual field identity. Per-peer certificates/keys remain required before field use.
- Local HMAC evidence manifests are only as strong as key custody and workstation security.
- A checksum embedded in a calibration profile provides provenance/error detection, not an external signature.

## Highest-priority pending tests

1. Negative RBAC and WebSocket authentication against a running stack.
2. V2X unauthorized source, replay, expiry, malformed JSON, and signature mutation.
3. MQTT ACL and mTLS rejection with an untrusted certificate.
4. Database migration/restore and audit mutation rejection.
5. Dependency, secret, container, and SBOM scans in network-enabled CI.
6. Camera freeze/corruption, storage-full, and queue saturation recovery.

No CRITICAL/HIGH result is declared cleared without executing the corresponding runtime or scanner test.
