# Perception Production Readiness

This project is engineered for measured improvement, not unprovable “perfect”
detection. A production release requires all controls below.

1. **Legal model use.** Ultralytics states that private/commercial use of its
   software or models requires its applicable commercial licence unless the
   entire project is released under AGPL-3.0. Confirm the deployment licence
   before field use.
2. **Data governance.** Train only on footage you are authorised to use; keep
   an immutable dataset version, licence/provenance record, and held-out camera
   sites/conditions.
3. **Dataset gates.** Run `training/validate_port_dataset.py`. It verifies
   YOLO syntax, class coverage, train/validation split leakage by image hash,
   missing labels, unmatched labels, and class scarcity.
4. **Measured evaluation.** Evaluate on held-out representative port video by
   class, day/night, weather, camera angle, object scale, and occlusion. Record
   precision, recall, mAP, false-alert rate, and latency. Set confidence
   thresholds from these results instead of guessing.
5. **Controlled release.** Complete a manifest with model hash, classes,
   dataset version/licence, and metrics. Use `promote_port_model.py` to copy an
   approved candidate atomically into `models/port/`.
6. **Runtime verification.** Set `MODEL_MANIFEST_PATH=/models/port/manifest.json`
   and `REQUIRE_MODEL_MANIFEST=true` for the custom port model. Startup then
   checks the model file hash and class contract before inference starts.
7. **Temporal confirmation.** The live service waits for three recent ByteTrack
   observations before publishing a new Track ID. Tune this with labelled field
   data; lower values reduce latency, higher values reduce one-frame false
   positives.
8. **Field acceptance.** Validate camera placement, focus, exposure, stream
   continuity, GPS/IMU clock synchronisation, calibration, retention policy,
   access control, incident response, and rollback before relying on events.

The LLM remains an optional advisory reviewer after deterministic events. It is
not a detector, tracker, trainer, model-release authority, or alert authority.
