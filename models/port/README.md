# Port vessel model

`sentinel-vessel-yolo11.pt` is the Git-LFS runtime checkpoint for the two
classes supported by this prototype:

- `small_boat`
- `cargo_vessel`

After cloning, retrieve the model bundle with `git lfs pull`. The default
`.env.example` already selects this model:

```ini
YOLO_MODEL=/models/port/sentinel-vessel-yolo11.pt
TARGET_OBJECT_CLASSES=small_boat,cargo_vessel
```

The vision worker normalises either label to the runtime category `vessel` for
tracking and deterministic rules. This checkpoint is a candidate model; retain
the training metadata, complete held-out evaluation, and obtain operator
approval before any operational use.
