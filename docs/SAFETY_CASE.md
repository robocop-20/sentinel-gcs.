# Sentinel safety case (development argument)

Top claim: within its stated development/bench operating envelope, Sentinel fails visibly and does not grant perception or AI autonomous control authority.

## Argument

1. **Observation is bounded and provenance-bearing.** Latest-frame capture prevents backlog; detections require class-specific and temporal gates; tracks/events carry timestamps, model and calibration hashes, source, correlation, and uncertainty status.
2. **Location and mission state are conservative.** Stale/mismatched telemetry produces no derived location. Invalid attitude disables the ray-plane path. Unknown accuracy is shown as unbounded. Mission routes are versioned and checked against restricted polygons including crossing legs.
3. **Operational decisions are deterministic and reviewable.** Geofence/risk/event code is separate from LLM review. Events have forward-only, justified human lifecycle transitions and cannot be silently deleted.
4. **Failures are isolated.** Vision, rules, storage, MQTT/V2X, LLM, and UI have bounded queues/freshness/circuits. Optional layer failure does not alter detector/tracker/risk output. Auditable mutations fail closed when audit persistence is unavailable.
5. **No direct hazardous actuation exists.** Mission prepare performs readiness only and reports `EXTERNAL_HARDWARE`; no MAVLink command/arming/upload adapter, weapon, target selection, or engagement function is present.
6. **Security protects safety state.** JWT/RBAC, service mTLS, MQTT TLS, V2X signatures/replay/allowlist, strict schemas, security headers, encrypted evidence, and container isolation reduce unauthorized modification.

## Evidence status

Source inspection, compilation, JavaScript/PowerShell syntax, Compose resolution, static UI contract, configuration policy smoke, and documentation traceability passed in the constrained run. Full Python tests, running services, browser screenshots, model/GPU benchmarks, HIL, controlled field validation, penetration test, and independent qualification did not run and remain explicit evidence gaps.

## Operating constraints

- DEVELOPMENT release only until the test ladder is executed.
- Never infer model accuracy from confidence.
- Never use approximate geolocation as a validated coordinate.
- Never enable V2X without unique provisioned peer identities/keys/certificates and allowlist.
- Never enable external LLM egress without approved data handling; advisory output is non-authoritative.
- Never connect a vehicle command adapter without separate HIL safety analysis and authorization.

The hazard log, fault matrix, traceability matrix, and final verification report are integral to this argument. This document is not military certification or formal safety approval.
