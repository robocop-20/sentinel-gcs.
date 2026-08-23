# Sentinel performance budget

Status: acceptance-budget definition. No value below is presented as a measurement. Runtime percentiles are `NOT MEASURED` in the current sandbox because Docker service access and GPU execution were unavailable.

| Path | Measurement boundary | Acceptance budget | Current measurement |
|---|---|---:|---|
| YOLO inference | inference start → result | configured field gate p95 ≤ 60 ms; ≥ 20 inferred FPS | NOT MEASURED |
| Camera end-to-end | capture timestamp → browser image presentation | project gate ≤ 100 ms where hardware permits | NOT MEASURED |
| Frame age | capture → inference selection | no queued backlog; latest item only | implementation inspected; runtime pending |
| Telemetry ingest | adapter receive → API accepted | define p50/p95/p99 under target packet rate | NOT MEASURED |
| Detection/event API | request receive → 2xx/202 | define after baseline workload | NOT MEASURED |
| WebSocket display | server broadcast → DOM/canvas update | no unbounded render queue or long task > 50 ms | NOT MEASURED |
| PostGIS track write | queue dequeue → commit | define after target storage hardware | NOT MEASURED |
| Event generation | confirmed track → event queued | deterministic and independent of LLM | NOT MEASURED |
| Evidence creation | crop request → encrypted artifact + manifest | must not block perception loop | NOT MEASURED |
| Map interaction | input → painted map | workstation p95 target ≤ 100 ms | NOT MEASURED |

## Required benchmark method

For each target hardware profile, run warm-up, then at least 1,000 samples or 10 minutes (whichever is longer). Record p50/p95/p99, maximum, sample count, hardware/OS/driver, model hash, image size, camera resolution/rate, active track count, database size, and container digests. Preserve raw samples under `reports/performance/<run-id>/`; summary JSON must reference raw-file SHA-256 hashes.

Vision benchmarking uses `training/benchmark_inference.py` and the exact candidate weights. The port release gate rejects mismatched model hashes. Browser performance requires PerformanceObserver long-task samples, preview paint timing, memory snapshots, and explicit viewport. Database measurement requires `EXPLAIN (ANALYZE, BUFFERS)` on representative spatial/event queries without production data mutation.

## Backpressure budgets

- Camera capture and API publication retain one latest frame/result.
- `PIPELINE_QUEUE_SIZE` is bounded; full ingress rejects with 503 rather than accumulating delay.
- Durable outbox is bounded by record count and bytes.
- Browser histories, event state, telemetry histories, tracks, evidence/advisory lists, WebSocket clients, and provider queues are bounded.
- Queue saturation, replacement counts, retry delay, circuit state, and dropped items must be exported and alerted before a field-readiness claim.

## Optimization rule

No optimization is accepted without before/after data from the same workload and hardware. Quality thresholds may not be reduced merely to improve FPS. 60 FPS is not claimed.
