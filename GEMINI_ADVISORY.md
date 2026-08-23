# Gemini Advisory Object and Event Review

Google Gemini is an optional seventh-layer adviser, not a detector or tracker.
The real-time path remains OpenCV -> YOLO11 -> ByteTrack. Gemini cannot modify
a ByteTrack ID, confidence, detection, geofence state, risk score, severity,
or V2X message.

The adviser can review one bounded local YOLO crop plus factual context after
either a high-risk local event or a confirmed vessel/vehicle/container track.
The latter route is rate-limited once per anonymous track and can operate
without GPS/LiDAR telemetry. It returns a structured object/scene cross-check
and short rationale. It may recommend extra authorised evidence to an operator,
but it never controls a safety-critical response.

It is prohibited from person identification, face matching, facial embeddings,
or named-person search. The separate local OpenCV YuNet layer may report
anonymous face boxes/landmarks/quality only when its licensed ONNX model is installed.

## Configure after explicit imagery approval

Use one Gemini API key locally in `C:\Users\ASUS\Downloads\fpv\.env`; never paste it into chat:

```ini
ENABLE_EVIDENCE_CAPTURE=true
ENABLE_LLM_VERIFICATION=true
LLM_PROVIDER=google
LLM_MODEL=gemini-3.6-flash
GEMINI_API_KEY=your-private-key
# Keep false until an authorised operator explicitly approves external image transfer.
ENABLE_EXTERNAL_LLM_EGRESS=false
# Optional non-person second opinion. These are never applied to people.
ENABLE_LLM_DETECTION_ADVISORY=false
LLM_ADVISORY_OBJECT_CLASSES=vessel,vehicle,container
LLM_ADVISORY_MIN_CONFIDENCE=0.60
LLM_ADVISORY_TRACK_COOLDOWN_S=90
```

After approval, change only the last setting to `true` and restart the API and
vision services. The adapter uses Gemini's `generateContent` image input and
structured JSON response. Provider failures leave all core layers running.
