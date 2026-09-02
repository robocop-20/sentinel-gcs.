# Runtime model bundle

This repository's private Git LFS storage contains the runtime model bundle
used by the local development stack:

- `yolo11s.pt` — generic COCO object detector
- `yolo11n-pose.pt` — local pose/fall-observation model
- `face/yunet.onnx` — face *detection* model only
- `person-verifier/.../fasterrcnn_mobilenet_v3_large_320_fpn-907ea3f9.pth`
  — local independent generic person checker
- `port/sentinel-vessel-yolo11.pt` — two-class small-boat and cargo-vessel
  detector trained for the port prototype

The vessel checkpoint is an engineering candidate, not an approved safety,
navigation, or enforcement model. Its training provenance and runtime contract
are recorded in [port/model-metadata.json](port/model-metadata.json).

No biometric reference data, camera addresses, API keys, database data,
evidence, or logs belong in this directory or repository.

For a cloned workspace using the default Compose configuration, this folder is
mounted read-only into the vision services at `/models`.
