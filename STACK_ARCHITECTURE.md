# Sentinel FPV Backend Architecture

This system is deliberately layered.  A slowdown or failure in telemetry, the
database, V2X, or an advisory provider does not block camera capture, YOLO, or
ByteTrack.

```text
OpenCV camera/video
        |
YOLO11 GPU detection -> ByteTrack anonymous persistent IDs -> face observation
        |                                                        |
        +-------------------- timestamped detections ------------+
                                 |
GPS + IMU + LiDAR (MAVLink) -> pose/range association -> geolocation
                                 |
                         geofence + risk + behaviour rules
                         /            |              \
                  PostGIS         MQTT/V2X      optional advisory review
```

## Implemented layers

| Layer | Component | Status and boundary |
|---|---|---|
| Camera/video | OpenCV latest-frame input | Live when the configured source is reachable. Old frames are discarded to prevent latency buildup. |
| Detection | YOLO11 on NVIDIA GPU | Standard model recognises people, boats/vessels, and common road vehicles. `container` is optional and requires a validated port model. |
| Tracking | ByteTrack | Uses a versioned two-threshold association policy and publishes only confirmed anonymous persistent IDs such as `camera-01-T-027`. |
| Face observation | Local YuNet face detector | Bounding box, landmarks, quality, blur, and anonymous person-track link only. It does not identify a person. |
| GPS/IMU/LiDAR | MAVLink bridge | Reads vehicle pose, attitude, velocity, link/battery telemetry, and downward LiDAR range when a flight controller is connected. |
| Geolocation | Timestamped pose/range fusion | Produces approximate locations; calibrated ray-plane mode needs verified camera intrinsics and mount transform. |
| Geofencing/risk | Deterministic rules | Detects entry/exit, quiet-hours risk, loitering, and proximity. Rules, not an LLM, dispatch alerts. |
| Storage | PostGIS | Persists sampled tracks and events independently of detection. |
| V2X | Signed MQTT envelope + relay | Shares event, object class, anonymous track ID, location, confidence, heading, velocity, altitude, and geofence context after it is configured. |
| LLM | Optional advisory object/scene review | Off by default. It can review only approved non-person object crops after a high-risk event; it cannot add detector classes, alter ByteTrack IDs, identify faces, or trigger alerts. |

## Activation without disrupting vision

The GPU vision service is independent and already runs using the GPU compose
override.  Start a hardware adapter only when that hardware is present:

```powershell
# GPS, IMU, and LiDAR from a MAVLink flight controller
& "D:\Docker\Desktop\resources\bin\docker.exe" compose `
  -f .\docker-compose.yml `
  --profile telemetry up -d telemetry

# V2X only after ENABLE_V2X, V2X_SOURCE_ID, and V2X_SHARED_SECRET are configured
& "D:\Docker\Desktop\resources\bin\docker.exe" compose `
  -f .\docker-compose.yml `
  --profile v2x up -d v2x
```

Check the exact live state without relying on the dashboard:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/capabilities
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

## Optional port fine-tuning

Fine-tuning is required only if you need a port-specific class such as
`container`, or significantly better performance in your own camera conditions.
It is not necessary for the standard person/vessel/vehicle classes.  The model
does not train from an LLM; it trains from authorised, labelled camera imagery.
Use `run_port_training_gpu.ps1` only after the local dataset has passed
validation.

## Explicitly not included

No face embedding, reference-face gallery, named-person lookup, or ArcFace
matching is part of this system.  Those functions would change the system from
anonymous surveillance into biometric identification and require a separate,
lawful programme with governance, consent/authority, accuracy evaluation, and
operator controls.
