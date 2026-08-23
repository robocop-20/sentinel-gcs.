# GPU Acceleration

The local host exposes an NVIDIA GPU through Docker Desktop. The GPU deployment
uses a separate CUDA-enabled image, leaving the CPU image available as a known
fallback.

## Enable live GPU inference

```powershell
cd C:\Users\ASUS\Downloads\fpv
& "D:\Docker\Desktop\resources\bin\docker.exe" compose `
  -f .\docker-compose.yml `
  -f .\docker-compose.face.yml `
  -f .\docker-compose.gpu.yml `
  --profile vision up --build -d vision
```

Verify that the container sees CUDA:

```powershell
& "D:\Docker\Desktop\resources\bin\docker.exe" compose `
  -f .\docker-compose.yml `
  -f .\docker-compose.face.yml `
  -f .\docker-compose.gpu.yml `
  --profile vision exec vision python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

The vision worker receives `YOLO_DEVICE=0`; it will report `device: 0` through
`/api/snapshot` metrics. Monitor inference latency and GPU memory before raising
`VISION_IMG_SIZE` or switching to a larger model.

## What GPU changes

GPU acceleration reduces inference latency and makes fine-tuning feasible. It
does not add missing object classes to the standard model. `container` still
requires the validated custom port model and labelled port dataset described in
`PORT_FINE_TUNING.md`.

The LLM is a separate optional network advisory layer. It is not accelerated by
this image and does not replace YOLO detection or ByteTrack tracking.
