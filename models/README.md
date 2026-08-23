# Runtime model bundle

This repository's private Git LFS storage contains the current generic runtime
weights used by the local development stack:

- `yolo11s.pt` — generic COCO object detector
- `yolo11n-pose.pt` — local pose/fall-observation model
- `face/yunet.onnx` — face *detection* model only
- `person-verifier/.../fasterrcnn_mobilenet_v3_large_320_fpn-907ea3f9.pth`
  — local independent generic person checker

No custom port-detection model is included because none has been validated for
release. No photographs, biometric reference data, camera addresses, API keys,
database data, evidence, or logs belong in this directory or repository.

For a cloned workspace using the default Compose configuration, this folder is
mounted read-only into the vision services at `/models`.
