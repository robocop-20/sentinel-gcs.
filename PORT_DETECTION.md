# Port Object Detection and Movement

## What works with the deployed standard YOLO11 model

The deployed `yolo11s.pt` model is configured for `person`, `boat`, `car`,
`truck`, `bus`, and `motorcycle`. Sentinel normalises `boat` to `vessel` and
road classes to `vehicle`. It can only report objects that are visible in the
camera frame; an indoor test view should not be expected to produce a boat or
vehicle detection.

## Fine-tuned maritime classes

Standard COCO YOLO11 has only the broad `boat` class; it cannot reliably
distinguish small boats from cargo vessels. For real port use, supply a
validated, licensed port-trained YOLO11 model with exactly `small_boat` and
`cargo_vessel` labels at for example
`C:\Users\ASUS\Downloads\fpv\models\port\port-yolo.pt`, then set in `.env`:

```ini
YOLO_MODEL=/models/port/port-yolo.pt
TARGET_OBJECT_CLASSES=person,boat,vessel,small_boat,cargo_vessel,car,truck,bus,motorcycle,vehicle
REQUIRE_MODEL_MANIFEST=true
```

The pipeline normalises both custom labels to the canonical `vessel` risk
category and gives them persistent ByteTrack IDs, while retaining the original
model class in the detection record. Do not replace the model until it has been
validated on representative port footage with documented precision and recall.

## Movement

Every current Track ID now reports:

- `motion.status`: `unknown`, `stationary`, or `moving`;
- `motion.speed_image_px_s`: smoothed image-plane pixel speed;
- `motion.image_heading_deg`: image-plane direction (0° = image-up).

These values are useful for camera monitoring but are not physical speed or
compass direction. GPS + IMU and calibrated camera geometry are required for
ground speed, real-world heading, geolocation, or collision-risk rules.

## LLM boundary

The LLM is disabled in the active deployment and does not run on frames or
assist YOLO. If enabled later, it remains an optional, gated advisory review of
authorised object evidence; it cannot alter detector output, tracking IDs, or
deterministic alerts.
