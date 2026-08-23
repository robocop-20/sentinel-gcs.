# Fault injection matrix

Status: test specification. `NOT RUN` means no outcome is claimed in this sandbox.

| ID | Fault | Expected detection / fail-safe | Recovery acceptance | Actual |
|---|---|---|---|---|
| FI-CAM-01 | camera disconnect | camera age degrades; no stale LIVE claim; reconnect backoff | fresh frames resume without process rebuild | NOT RUN |
| FI-CAM-02 | corrupt/truncated MJPEG | invalid bytes discarded; decode failures counted | next complete JPEG accepted | NOT RUN |
| FI-CAM-03 | frozen frame | frozen/age indication; rules do not receive new timestamps | new sequence clears degraded state | NOT RUN |
| FI-GPS-01 | GNSS loss/stale | NO FIX/STALE; no new geolocation | fresh matching vehicle sample restores | NOT RUN |
| FI-IMU-01 | attitude loss | ray-plane mode not used; quality degraded | valid attitude restores calibrated path | implementation check passed; runtime NOT RUN |
| FI-LIDAR-01 | range loss/out-of-range | N/A/stale; never zero; altitude fallback marked approximate | fresh valid range reassociated | NOT RUN |
| FI-MAV-01 | heartbeat loss/reorder | telemetry age and anomaly finding | reconnect without duplicate vehicle | NOT RUN |
| FI-DB-01 | database restart | storage circuit/backlog; critical actions requiring audit fail closed | durable backlog drains in order | NOT RUN |
| FI-MQTT-01 | broker outage | transport unhealthy; bounded retry/outbox | reconnect and QoS acknowledgement | NOT RUN |
| FI-V2X-01 | invalid signature | reject, count, security finding | no state/event acceptance | NOT RUN |
| FI-V2X-02 | replay/duplicate/expired | reject by message ID, sequence, and expiry | subsequent fresh message accepted | NOT RUN |
| FI-LLM-01 | timeout/rate limit | advisory unavailable/circuit open; core unchanged | bounded retry then recovery | NOT RUN |
| FI-LLM-02 | malformed verdict | reject output; no risk/track mutation | later valid advisory displayed | NOT RUN |
| FI-EVD-01 | evidence write failure | finding/health degradation; event remains | later write succeeds; no corrupt artifact | NOT RUN |
| FI-DISK-01 | storage full simulation | bounded failure; no infinite retry/memory growth | operator remediation then controlled resume | NOT RUN |
| FI-CERT-01 | expired/untrusted certificate | TLS/mTLS connection rejected | rotated trusted material restores | NOT RUN |
| FI-WS-01 | browser/backend disconnect | explicit RETRY state and capped backoff | re-authenticated snapshot reconciles state | NOT RUN |
| FI-API-01 | backend restart | gateway readiness fails; browser does not show LIVE | health/readiness and snapshot recover | NOT RUN |
| FI-QUEUE-01 | ingress saturation | 503/full metric; stale work not queued | queue returns below threshold | NOT RUN |

## Execution record

Each run must capture UTC start/end, build/model/calibration hashes, injected mechanism, expected/observed detection time, operator indication screenshot/log, data loss/duplication, recovery time, residual queue depth, and PASS/FAIL. Run in the test ladder: unit → recorded replay → SITL → HIL → controlled bench → controlled field. Never inject a fault into an uncontrolled vehicle.
