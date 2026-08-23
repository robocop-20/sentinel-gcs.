# Model and Evidence Registry

The system reports operational outputs, not claims of perfect accuracy. Every
persisted/live object record contains `track_id`, normalized `class`, original
`model_class`, `confidence` (0–1), bounding box, source camera, observation
timestamp, optional location, and risk factors.

| Layer | Runtime/code | Identifies or measures | Evidence emitted |
|---|---|---|---|
| Capture | `app/vision_runtime.py` | OpenCV frame from IP/RTSP/USB source | capture FPS, stale-frame drops, source errors |
| Object perception | `app/vision_worker.py` + Ultralytics YOLO model in `models/` | `person`, `boat`→`vessel`, `car/truck/bus/motorcycle`→`vehicle` | original model label and detection confidence |
| Tracking | `bytetrack.yaml` selected in `app/vision_worker.py` | Same object across frames | persistent camera-scoped `track_id` |
| Face detection (optional) | `app/face_detector.py` + licensed ONNX model + `requirements-face.txt` | face bounding boxes only | face confidence, box, landmarks; no identity |
| GPS/IMU | `app/mavlink_bridge.py` | position, attitude, speed, link and battery | timestamped telemetry |
| LiDAR | `app/mavlink_bridge.py` | range and sensor orientation | timestamped range measurement |
| Geolocation | `app/geolocation.py` | estimated world location of a track | method and `approximate` flag |
| Geofence/risk | `app/geofence.py`, `app/risk_engine.py`, `app/events.py` | restricted-zone transition and transparent risk | event, severity, score, factors |
| Persistence/transport | `app/persistence.py`, `app/mqtt.py`, `app/v2x.py` | durable and signed delivery | PostGIS record / MQTT or V2X envelope |

`confidence` is the detector's model score, not a probability of real-world
truth. Tune `DETECTION_CONFIDENCE` from labelled field data, separately for
each camera position, illumination condition, and target type.
