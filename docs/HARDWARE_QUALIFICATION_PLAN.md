# Hardware qualification plan

Status: preparation complete; execution is `EXTERNAL_HARDWARE`, `EXTERNAL_FIELD_TEST`, and where applicable `EXTERNAL_CERTIFICATION`.

This plan prepares repeatable environmental verification without claiming MIL-STD-810 qualification. The procuring authority and accredited laboratory must select applicable methods, severities, durations, mounting, operating profiles, sample count, and acceptance limits for the actual production hardware configuration.

## Test article and configuration control

Before any exposure, record the unit serial number, workstation/airframe configuration, Sentinel release provenance, container and model hashes, cable set, antenna, camera, GNSS/IMU/LiDAR, power source, storage state, calibration hashes, test-fixture drawing, and photographs. Seal the release manifest and pre-test evidence manifest. A hardware or software change creates a new configuration and invalidates reuse of unreviewed results.

## Common pre/post functional profile

1. Verify visual inspection, insulation/grounding as applicable, storage health, clock synchronization, certificates, and calibration status.
2. Run controlled camera replay and confirm frame freshness, detection publication, anonymous tracking, event/evidence creation, and evidence verification.
3. Run MAVLink/GNSS/IMU/LiDAR simulators, then actual connected sensors where safe.
4. Exercise link interruption/recovery and controlled power cycling.
5. Record CPU/GPU temperature, throttling, memory, storage errors, service restarts, frame drops, sensor age, and alert/recovery times.
6. Re-run the same profile after exposure and compare signed artifacts. Any unplanned reset, silent corruption, unsafe state, enclosure breach, or loss of required function is a failure pending disposition.

## Environmental matrix

| Exposure | Instrumentation and operation | Evidence | Pass/fail definition |
| --- | --- | --- | --- |
| High/low operating temperature | Chamber, internal/ambient probes, production power and workload | Temperature/time trace, health metrics, logs, pre/post functional result | Limits selected by authority/lab; no unsafe state or silent data corruption; required functions within approved budget |
| Storage temperature | Powered-off controlled exposure, inspected restart | Exposure trace, visual inspection, boot/storage/evidence verification | No physical damage, loss of configuration, or verification failure |
| Humidity/condensation | Controlled ramp; dew-point monitoring; no unsafe energization | Chamber trace, insulation/enclosure inspection, functional profile | No ingress/corrosion/short, and post-test functions pass approved criteria |
| Vibration | Operational and non-operational axes using qualified fixture | Accelerometer/control trace, fixture resonance survey, logs | No loose hardware, connector interruption, unsafe reset, or out-of-budget degradation |
| Mechanical shock | Selected pulse/axis/sample plan | Calibrated pulse trace, high-speed/fixture evidence, inspection | No structural damage, unsafe state, data loss, or failed functional profile |
| Dust | Representative enclosure/cooling arrangement | Particle/exposure log, filter/thermal inspection | No hazardous ingress, cooling blockage beyond approved limit, or functional loss |
| Water/rain | Enclosure-specific method with protected test setup | Flow/pressure/duration record, ingress inspection | Ingress class and acceptance criteria selected by authority/lab; no energized hazard or functional loss |
| Altitude/low pressure | Pressure chamber with thermal/power monitoring | Pressure/temperature trace, storage and cooling metrics | No arcing, unsafe thermal condition, storage error, or approved-function failure |
| Combined profiles | Only after single-factor characterization | Full synchronized traces and incident log | Criteria issued in the approved qualification procedure |

## Safety and recovery

- Each procedure requires a hazard review, emergency stop, chamber/fire precautions, safe battery handling, and named test director.
- Sentinel must present stale/offline/degraded states; it must not fabricate LIVE data during sensor or link loss.
- Preserve the failed state before repair. Record nonconformance, root cause, corrective action, regression evidence, and retest disposition.
- Back up evidence and databases before testing. Restoration must occur only into an isolated environment and must verify checksums and core rows.

## Deliverables

Approved procedure, calibration certificates, raw instrumentation files, Sentinel logs/metrics, photos, configuration manifest, anomalies, corrective-action record, signed results, and authority/laboratory disposition. Formal qualification remains external until those artifacts exist.
