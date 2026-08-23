# Single-point failure and FMEA analysis

| Item / failure mode | Cause | Local effect | System effect | Detection | Mitigation/recovery | Current status |
|---|---|---|---|---|---|---|
| single camera/source | power/network/app loss | no frames | no new detection | frame age/reconnect metrics | explicit degraded state; reconnect; add independent camera externally | hardware redundancy external |
| MJPEG bridge | process/decoder failure | Docker feed stops | vision waits | bridge logs + camera age | host task restart; latest complete JPEG reconstruction | bench test pending |
| vision worker | model/GPU/process failure | no new tracks | rules receive nothing | health/readiness/model errors | isolated restart; no stale frame queue | runtime test pending |
| one detector model | domain shift/corrupt weights | false/missed boxes | event quality loss | manifest/hash and held-out metrics | release gate, rollback, optional local verifier | dataset external |
| ByteTrack state | restart/occlusion | anonymous ID changes | track fragmentation | lifecycle and replay metrics | lost buffer/reacquisition; no false biometric continuity | replay pending |
| flight telemetry link | MAVLink loss | stale state | geolocation disabled/degraded | heartbeat/packet age | reconnect, per-vehicle association, N/A UI | HIL pending |
| GNSS/IMU/LiDAR sensor | invalid/lost data | location/range unavailable | no precise geolocation | quality/freshness and anomaly finding | fail to N/A/unbounded; sensor replacement | hardware pending |
| API service | crash/restart | ingestion/UI unavailable | operational interruption | gateway health/browser retry | restart policy, durable queue, snapshot resync | fault test pending |
| PostGIS | outage/corruption | persistence/audit unavailable | mutations fail closed, backlog grows | pool/circuit/health | bounded durable outbox, backup/restore | restore test pending |
| durable SQLite outbox | disk corruption/full | retry unavailable | event delivery loss risk | queue errors/capacity | checksum/backup, fail-safe alert, disk remediation | fault test pending |
| MQTT broker | outage | no transport/V2X | local UI/rules continue | connection/outbox metrics | bounded retry/backoff and QoS 2 | fault test pending |
| shared V2X secret | compromise | peer spoofing | remote false event risk | signature cannot identify compromised peer | per-peer keys/certs required, allowlist/rotation | credential provisioning external |
| evidence key/store | key loss/full disk | cannot decrypt/write | custody gap | write/verify failure | offline protected backup, rotation/custody procedure | recovery test pending |
| gateway certificate | expiry | edge unavailable | browser cannot connect | TLS/expiry monitoring | planned rotation and rollback | PKI drill pending |
| operator workstation/browser | crash/disconnect | display/control loss | no human review | connection state | reconnect/snapshot; independent workstation plan | field procedure external |
| optional LLM/provider | timeout/malformed | no advisory | core remains unchanged | worker/circuit metrics | fail isolated, bounded retry | unit/runtime pending |

No listed single point is treated as eliminated solely by a restart policy. Field redundancy, spares, network topology, power, clocks, and independent operator procedures are `EXTERNAL_HARDWARE/FIELD_TEST` responsibilities.
