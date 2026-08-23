# Sentinel hazard log

Scale: probability `P1 rare` to `P5 frequent`; severity `S1 negligible` to `S5 catastrophic`; qualitative risk is engineering triage, not field-derived probability. Residual values require field confirmation.

| ID | Hazard / cause | Initial risk | Mitigation | Verification | Residual risk |
|---|---|---|---|---|---|
| H-001 | stale telemetry associated with a new frame | P3/S4 High | per-vehicle bounded history and max timestamp skew; no match means no derived location | association unit/replay plus delayed-packet fault | P1/S4 Medium, field TBD |
| H-002 | GNSS loss or invalid fix shown as usable | P3/S4 High | fix taxonomy, age, NO FIX/STALE UI, geolocation suppression when absent | telemetry/UI stale tests | P1/S4 Medium, HIL TBD |
| H-003 | false or missed object detection | P4/S3 High | class gates, temporal confirmation, independent local marginal-person veto, dataset evaluation | held-out precision/recall/background tests | BLOCKED_DATASET |
| H-004 | anonymous ID switch/fragmentation | P4/S3 High | ByteTrack, lost buffer, class/motion consistency, explicit lifecycle | replay IDF1/switch benchmark | BLOCKED_DATASET/FIELD_TEST |
| H-005 | false security event | P3/S3 High | deterministic provenance/rules, dedup, forward human review, no autonomous action | rule/event workflow tests | P1/S3 Medium |
| H-006 | camera disconnect/corruption/freeze | P4/S3 High | latest-frame reconstruction, reconnect/backoff, frame age/degraded state | FI-CAM-01..03 | P2/S3 Medium, bench TBD |
| H-007 | PostGIS unavailable | P3/S3 High | isolated circuit/durable queue; auditable operator mutations fail closed | restart/backlog/restore fault | P1/S3 Medium, runtime TBD |
| H-008 | MQTT/V2X outage or forged peer data | P3/S4 High | optional transport isolation, mTLS/HMAC/expiry/replay/allowlist/outbox | broker and V2X negative tests | P1/S4 Medium, field identity TBD |
| H-009 | evidence loss/tampering | P2/S4 High | AES-GCM, hashes, HMAC manifest, atomic writes, legal hold, audit | corruption/write-full/restore tests | P1/S4 Medium, custody TBD |
| H-010 | LLM failure or unsafe recommendation | P4/S2 Medium | explicit egress, strict output, circuit breaker, advisory-only data flow | timeout/malformed tests and architecture inspection | P1/S2 Low |
| H-011 | certificate/key expiry or compromise | P2/S4 High | mTLS/TLS verification, separate secrets, reject invalid trust | expiry/rotation drill | P1/S4 Medium, PKI process TBD |
| H-012 | disk/memory/queue exhaustion | P3/S3 High | bounded queues/history/connections, retention, circuit breakers, read-only roots | saturation and soak tests | P1/S3 Medium, runtime TBD |
| H-013 | browser/backend disconnect masks state | P3/S3 High | RETRY state, capped backoff, snapshot reconciliation, freshness labels | disconnect/restart E2E | P1/S3 Medium, browser TBD |
| H-014 | geolocation false precision/calibration mismatch | P4/S4 High | camera-bound checksummed profiles, aspect check, `UNCERTAINTY UNBOUNDED` until validated | profile/unit plus reference-target procedure | P2/S4 High, FIELD_TEST |
| H-015 | invalid mission crosses restricted zone | P2/S5 High | versioned validation of points and route segments; no upload adapter | unit and controlled HIL before adapter | P1/S5 Medium, HIL TBD |

Risk acceptance requires a named authority, configuration/build/model hashes, executed verification evidence, expiration/review date, and operating constraints. No hazard is closed by an LLM verdict.
