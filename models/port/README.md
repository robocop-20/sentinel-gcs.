# Port Model Release Folder

Place only a validated custom model here as `port-yolo.pt`. Its labels must use
the training contract: `person`, `vessel`, `vehicle`, and `container`.

Before copying a candidate here, run dataset validation and held-out evaluation,
record the model SHA-256 and metrics in a completed model manifest, and obtain
operator approval. The running vision service should then use:

```ini
YOLO_MODEL=/models/port/port-yolo.pt
TARGET_OBJECT_CLASSES=person,vessel,vehicle,container
```

No image, annotation, or model is uploaded by this repository's training tools.
