# EMI/EMC qualification plan

Status: engineering preparation only. No MIL-STD-461, CE, FCC, or other EMC compliance is claimed.

An accredited laboratory and the procuring authority must select the applicable conducted/radiated emissions and susceptibility methods, frequency ranges, limits, modulation, dwell, cable layout, grounding, bonding, antenna distance, safety interlocks, and margins for the final hardware installation.

## Controlled configuration

Freeze and record the enclosure, power supply, filters, cable lengths/shield termination, grounding/bonding, camera, GNSS/IMU/LiDAR, radios, compute/GPU/storage, software/container/model hashes, operating mode, and test-facility setup. Photograph every cable and termination. Any change requires impact review and normally a retest.

## Operational modes

- Maximum compute/GPU and storage activity with recorded camera replay.
- Live camera decode/inference/annotation where facility rules permit.
- MAVLink, MQTT, V2X and telemetry traffic at bounded representative rates.
- GNSS receive and IMU/LiDAR acquisition with safe simulators or shielded sources.
- Idle, boot, reconnect, degraded-link, and evidence-write modes.

## Test matrix

| Area | Observe | Sentinel-specific failure indicators |
| --- | --- | --- |
| Conducted emissions | Power/IO line spectrum and operating mode | Load-dependent peaks, resets, storage or network errors |
| Radiated emissions | Enclosure/cable radiation | GPU/camera/radio harmonics correlated with workload |
| Conducted susceptibility | Injected disturbances on power/IO | Silent sensor corruption, frame loss, false LIVE state, service restart |
| Radiated susceptibility | Field exposure across selected bands | Detection corruption, tracking discontinuity, clock/telemetry age errors, link loss |
| ESD/transients where applicable | Contact/air discharge and power transients | Unsafe reset, evidence corruption, configuration loss, stuck control, recovery failure |
| Interoperability/co-site | Simultaneous onboard transmitters | GNSS desense, camera artifacts, V2X/MAVLink loss, thermal throttling |

## Instrumentation and correlation

Synchronize facility time with Sentinel UTC and monotonic timestamps. Capture receiver/analyzer data, injection level, antenna/probe position, power quality, service logs, Prometheus metrics, camera frame age, decode failures, inference latency, track/event counts, telemetry age, packet loss, storage errors, and health-state transitions. Mark each dwell with a correlation ID so an anomaly can be traced through frame → detection → track → event → evidence.

## Acceptance and anomaly handling

Numeric limits and functional-performance categories must come from the approved external test procedure; they are not invented here. At minimum there must be no unsafe physical behavior, silent evidence corruption, unauthorized command, fabricated LIVE state, or unrecoverable configuration/data loss. Required operational functions and recovery time must meet approved budgets. Stop on a safety hazard, preserve evidence, open a nonconformance, reproduce under controlled conditions, fix, regression-test, and rerun affected cases.

## Pre-compliance sequence

1. Bench near-field scan and power-line review.
2. Cable/shield/grounding design review.
3. Pre-compliance chamber sweep in all operating modes.
4. Corrective changes plus software regression and thermal recheck.
5. Accredited formal test on production-representative articles.
6. Controlled report, deviations, retest, and authority disposition.

Formal compliance remains `EXTERNAL_CERTIFICATION` until signed accredited evidence exists.
