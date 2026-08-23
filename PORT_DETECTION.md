# Port Object Detection and Movement

## What works with the deployed standard YOLO11 model

The deployed `yolo11s.pt` model is configured for `person`, `boat`, `car`,
`truck`, `bus`, and `motorcycle`. Sentinel normalises `boat` to `vessel` and
road classes to `vehicle`. It can only report objects that are visible in the
camera frame; an indoor test view should not be expected to produce a boat or
vehicle detection.

## Containers

Standard COCO YOLO11 does **not** contain a shipping-container class. For real
port use, supply a validated, licensed port-trained YOLO11 model at for example
`C:\Users\ASUS\Downloads\fpv\models\port\port-yolo.pt`, with labels such as `container`,
`shipping_container`, or `vehicle`, then set in `.env`:

```ini
YOLO_MODEL=/models/port/port-yolo.pt
TARGET_OBJECT_CLASSES=person,boat,container,shipping_container,vehicle,car,truck,bus,motorcycle
```

The pipeline already normalises the container labels to `container` and gives
them persistent ByteTrack IDs. Do not replace the model until it has been
validated on representative port footage with documented precision/recall.

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
