# Sentinel layer fail-safe policy

This runtime uses failure containment, not fail-open decision making. The local
OpenCV -> YOLO -> ByteTrack -> fusion -> deterministic rules path remains the
only alert authority. External LLM responses are optional evidence and advice.

| Layer | Failure signal | Contained response |
|---|---|---|
| OpenCV video | stale heartbeat, malformed/end-of-stream feed | mark visual coverage unavailable; reconnect capture; never replay old frames |
| YOLO detection | no fresh frames, model error, required manifest mismatch | suppress detector-ready claims; never replace a detection with LLM text |
| ByteTrack | detector unavailable, weak track mean, unstable class, or insufficient observations | expire stale anonymous tracks; publish only strong multi-frame evidence; do not invent persistent IDs |
| Face observation | model/init/frame error | skip face observations for that frame; keep YOLO/ByteTrack active; run privacy blur on preview frames when a person is present |
| Local pose/fall | pose model unavailable or temporal threshold not met | no fall event; retain normal object tracking |
| GPS/IMU/LiDAR fusion | absent or time-skewed telemetry/range | keep detections unlocated; do not infer geofence state from pixels |
| Geofence/risk rules | worker stopped or queue pressure high | preserve deterministic authority and shed optional advisory work |
| PostGIS | connection/write failure | live processing continues; isolated bounded retry queue records errors |
| MQTT/V2X | broker unavailable, unsigned/stale/replayed envelope | keep local alerting active; reject invalid V2X; report publish loss; no device commands |
| Object LLM | timeout, rate limit, provider error | bounded retry, circuit breaker, unavailable advisory; local result unchanged |
| Security LLM | timeout, rate limit, provider error | latest-only queue, circuit breaker, unavailable summary; finding unchanged |

Operational status is available at `GET /api/failsafe`. A healthy runtime report
is not a certification. Release still requires labelled port data, camera and
sensor calibration, fault-injection tests, soak tests, security review, and
authorised field acceptance.

The bundled anonymous MQTT listener is development-only and is bound to
`127.0.0.1`. A real V2X deployment must supply broker authentication, TLS/mTLS,
certificate rotation, network segmentation, and authority-operated endpoints.
