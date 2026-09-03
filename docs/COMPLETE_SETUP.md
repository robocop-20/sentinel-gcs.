# Complete Sentinel setup

This guide starts a local Sentinel development stack from the private
repository. It is for authorised operators only. It does not make the system a
certified safety, navigation, port-security, aviation, or enforcement product.

## What is in the repository

The repository contains the source code, Docker configuration, documentation,
the FPV hardware photographs, the two-class vessel checkpoint, and its curated
training dataset.

The model and training images use **Git LFS**, so Git LFS must be installed.
Personal configuration is intentionally not versioned: every operator creates
their own `.env` and camera source locally.

| Need | Download from Git LFS |
| --- | --- |
| Run the vessel detector | `models/**` |
| Train or evaluate the vessel detector | `models/**` and `training/datasets/port/**` |

## 1. Install prerequisites

Install these on the workstation:

- Windows 11 and PowerShell 5.1 or later
- [Git for Windows](https://git-scm.com/download/win)
- [Git LFS](https://git-lfs.com/)
- Docker Desktop with the WSL 2 backend
- An authorised network path to the camera source
- An NVIDIA GPU and NVIDIA Container Toolkit only for GPU inference or training

Open Docker Desktop and wait until it reports that the engine is running before
starting Sentinel.

## 2. Clone the private repository

In PowerShell, choose a folder with enough free space, then run:

```powershell
$env:GIT_LFS_SKIP_SMUDGE = "1"
git clone https://github.com/robocop-20/sentinel-gcs..git
cd sentinel-gcs
git lfs install
Remove-Item Env:GIT_LFS_SKIP_SMUDGE
```

This first clone retrieves lightweight Git-LFS pointers. The next section lets
you download only the LFS files needed for your role.

### Run-only installation

Download just the model bundle required to run the stack:

```powershell
git lfs pull --include="models/**" --exclude="training/datasets/port/**"
```

### Training installation

Download the model bundle and the curated port-training dataset:

```powershell
git lfs pull
```

The training dataset is about 103 MB. If you need to check it after download:

```powershell
python training\validate_port_dataset.py `
  --dataset-root training\datasets\port `
  --report $env:TEMP\sentinel-port-dataset-validation.json
```

## 3. Create your local configuration

Create a private local configuration file:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env`. It may contain passwords, tokens, and local service
settings. The supplied template defaults to the repository vessel model:

```ini
YOLO_MODEL=/models/port/sentinel-vessel-yolo11.pt
TARGET_OBJECT_CLASSES=small_boat,cargo_vessel
```

Before use, set unique local values for at least:

- `POSTGRES_PASSWORD`, and the matching password in `DATABASE_URL`
- `MJPEG_BRIDGE_TOKEN`
- any optional MQTT or advisory-provider credentials you enable

Keep optional external advisory and image egress features disabled unless an
authorised operator explicitly approves them.

## 4. Configure the camera source

Set the source using the provided command. It stores the address only in the
local ignored file `config\camera-source.txt`:

```powershell
.\set_camera_source.ps1 -Source <IP-or-URL>
```

Examples:

```powershell
.\set_camera_source.ps1 -Source 192.168.1.100:8080
.\set_camera_source.ps1 -Source rtsp://camera.example.local:554/stream
```

Use only an authorised camera. Never add a camera address to Git, documentation,
or a support message.

## 5. Start Sentinel

Run the normal launcher:

```powershell
.\start_sentinel.ps1
```

The launcher checks Docker, checks the local camera configuration, starts the
authenticated camera bridge, builds/starts the Compose services, and waits for
the API readiness endpoint.

Useful variants:

```powershell
# Use CPU vision even when an NVIDIA GPU is available.
.\start_sentinel.ps1 -CpuVision

# Start without automatically opening the browser.
.\start_sentinel.ps1 -NoBrowser

# Also enable configured telemetry and V2X profiles.
.\start_sentinel.ps1 -WithTelemetry -WithV2X
```

## 6. Verify the stack

Open the local console at `http://localhost:8080/`, then run:

```powershell
Invoke-RestMethod http://localhost:8080/readyz
docker compose -f docker-compose.yml --profile vision ps
```

If the readiness endpoint fails, inspect the relevant service logs:

```powershell
docker compose -f docker-compose.yml logs --tail 100 gateway api vision
```

## 7. Vessel-model contract

The included candidate model has exactly two labels:

- `small_boat`
- `cargo_vessel`

The runtime converts both labels to the canonical `vessel` category for
tracking and deterministic rules. The checkpoint is an engineering candidate;
validate it on representative authorised camera footage before operational use.
See [the model metadata](../models/port/model-metadata.json) and
[port fine-tuning guide](../PORT_FINE_TUNING.md).

## Troubleshooting

### Docker Desktop is not running

Start Docker Desktop, wait for its engine to become available, then rerun
`./start_sentinel.ps1`. Do not run a second Sentinel stack from another folder
against the same camera bridge port.

### Docker Desktop shows an unexpected error

The Docker Desktop application and its local images, caches, containers, and
volumes are not GitHub project files. If they are disposable, Docker Desktop's
**Reset to factory defaults** option can remove them and reclaim local storage.
That action permanently deletes Docker data; it does not affect the repository,
but it requires rebuilding the stack afterward.

### Git LFS files are missing

Run:

```powershell
git lfs install
git lfs pull
```

Use `git lfs ls-files` to confirm that the model and, when needed, the dataset
are present.

### Local configuration was accidentally changed

Keep the private `.env` and `config\camera-source.txt` local. Restore only from
your own secure local backup; do not copy another operator's settings.

## Update an existing installation

From the repository folder:

```powershell
git pull --ff-only
git lfs pull
.\start_sentinel.ps1
```

Review changes to `.env.example` before manually applying relevant non-secret
settings to your existing private `.env`.
