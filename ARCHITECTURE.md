# Backend Architecture

## Execution layers

```text
Video/IP camera ─┐
                 ├─ Perception adapter: OpenCV -> YOLO11 -> ByteTrack -> POST /api/detections (202)
MAVLink/LiDAR ───┼─ Sensor adapter: GPS + IMU + LiDAR -> POST /api/telemetry and /api/range
                 │
                 ▼
           [Ingress queue]      bounded; overload returns 503 rather than unbounded memory use
                 ▼
           Fusion worker        nearest-pose association, fresh LiDAR selection, ray/flat-plane projection
                 ▼
           Rules worker         geofence transition and deterministic risk factors
              ┌──────┴──────┐
              ▼             ▼
       Storage queue     Egress queue
              ▼             ▼
        PostGIS worker  MQTT / signed V2X worker
```

## Fault boundaries

- Capture and YOLO do not depend on the database, MQTT, or dashboard.
- PostGIS failures are retried by the storage layer; track and event writes are idempotent.
- MQTT/V2X failures are isolated to the egress layer.
- Every queue is bounded. `GET /api/health` exposes each queue depth, worker liveness, errors, and dropped work.
- A `503` on `/api/detections` means the system is saturated; the vision worker should lower `FRAME_INTERVAL`, reduce model size, or the operator should raise hardware capacity. Silent backlog growth is not allowed.

## Contracts between layers

| Producer | Contract | Consumer |
|---|---|---|
| Perception | DetectionBatch | Fusion |
| Sensor adapter | Telemetry and RangeMeasurement | Fusion |
| Fusion | ProcessedTrack | Rules, PostGIS, MQTT |
| Rules | Event | PostGIS, MQTT, V2X |

The only cross-layer interfaces are these typed Pydantic schemas and MQTT event envelopes. Device drivers and model libraries are never imported by the API image.

## Deployment rule

Run USB capture in the native Windows vision adapter. Run network RTSP in the optional Docker vision service. Use the base Docker stack for the API, PostGIS, MQTT, and optional V2X relay.
