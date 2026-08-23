# Field-readiness evidence plan

This project must be presented as a **prototype until the checks below have
measured evidence**. A running dashboard, an LLM response, or a single camera
demo is not proof of operational readiness.

## Runtime gate

`GET /api/readiness` returns a transparent `field_ready` or
`not_field_ready` result. It checks a live video source, inference FPS,
end-to-end latency, a hash-verified released model, fresh telemetry, calibrated
ray-plane geolocation, PostGIS, and MQTT.

The initial targets derived from the executive summary are at least 20 FPS and
at most 100 ms end-to-end latency. They are acceptance limits, not claims about
the current RTX 2050 prototype.

## Required evidence before a field pitch

1. **Video and compute:** replace an intermittent phone/MJPEG bridge with the
   intended RTSP, USB capture, or GStreamer/V4L2 input. Benchmark with the
   target camera resolution and record p50/p95 latency, dropped frames, and GPU
   memory. The current 4 GB RTX 2050 is a development baseline; a deployment
   target should be sized from this measurement, commonly an NVIDIA GPU with at
   least 8 GB VRAM.
2. **Detection:** create an authorised, labelled field dataset across day/night,
   glare, weather, occlusion, ranges, camera angles, vessels, vehicles,
   containers, people, and hard negatives such as blankets. Train only through
   the guarded port-model workflow; publish held-out per-class precision,
   recall, false-alarm rate, and mAP.
3. **Tracking:** assess ID switches, fragmentations, time-to-confirm, and track
   continuity on held-out recorded missions. Tune ByteTrack only from these
   measurements.
4. **Geolocation:** connect real MAVLink GPS/IMU and LiDAR, calibrate camera
   intrinsics/extrinsics, and validate against surveyed ground-control points.
   Do not present flat-ground approximations as precise target coordinates.
5. **Security and resilience:** use authenticated TLS/mTLS transport, unique
   credentials, key rotation, access control, encrypted retention, audit logs,
   backup/rollback drills, and offline-loss behaviour tests. The local MQTT
   broker and Docker Desktop setup are not a production security boundary.
6. **Human review:** retain deterministic rules as the alert authority. Gemini
   may provide a non-person object advisory only; it is not part of detection,
   tracking, release approval, or alert control. Local face observation stays
   anonymous; identity matching is not included.

## Pitch-safe wording

Use: “a layered prototype with measurable acceptance gates and a path to field
validation.” Do not use: “100% accurate”, “military grade”, or “operationally
approved” until independent authorised test evidence supports those claims.
