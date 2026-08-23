# Real-Time Performance Contract

The worker is designed to minimize *age of analysed video*, not to promise an
unmeasured frame rate. It uses a latest-frame capture slot and a latest-batch
API slot. When inference or delivery is slower than the source, older frames
are discarded and counted in `frames_dropped_for_latency` rather than queued.

Read `GET /api/snapshot` → `vision_metrics` while the worker is running:

- `capture_fps`: camera delivery rate.
- `inference_fps` and `last_inference_ms`: actual model speed on this hardware.
- `last_end_to_end_ms`: camera capture to completed inference age.
- `frames_dropped_for_latency`: deliberate stale work dropped to remain live.
- `last_detection_count`, and each track's `class`, `model_class`, `confidence`, and `track_id`: what was identified.

Use `YOLO_MODEL=/models/yolo11n.pt` for a CPU-first low-latency baseline,
`yolo11s.pt` for the default balance, and a measured GPU deployment for larger
models. Do not claim a latency or detection-quality SLA until representative,
labelled field video has been benchmarked. Set `VISION_IMG_SIZE`,
`DETECTION_CONFIDENCE`, `FRAME_INTERVAL`, and `VISION_CPU_THREADS` from those
measurements—not by guesswork.
