# Team setup

This guide is for authorised members of the private Sentinel GCS repository.
Each operator uses their own local configuration and camera source; do not copy
another operator's `.env`, credentials, evidence, or camera URL.

## Prerequisites

- Windows 11 with PowerShell 5.1 or newer
- Docker Desktop with the WSL 2 backend running
- Git and [Git LFS](https://git-lfs.com/)
- A local network route to the authorised camera source
- NVIDIA Container Toolkit only when GPU inference is required

## Clone and prepare

```powershell
git clone https://github.com/robocop-20/sentinel-gcs..git
cd sentinel-gcs
git lfs install
git lfs pull
Copy-Item .env.example .env
```

Set unique local values in `.env` before starting, especially PostgreSQL,
broker, bridge-token, and any optional advisory provider credentials. Do not
commit `.env`.

## Configure the camera

Use the single dynamic camera-source command:

```powershell
.\set_camera_source.ps1 -Source 192.168.1.100:8080
```

It writes the protected local `config\camera-source.txt` file. You may provide
an IP, `IP:port`, or a complete HTTP(S)/RTSP(S) stream URL. This file is ignored
by Git so every operator can use a different camera safely.

## Start and verify

```powershell
.\start_sentinel.ps1
Invoke-RestMethod http://localhost:8080/readyz
```

Open `http://localhost:8080/` only on the local workstation. Do not expose the
camera or API port directly to the Internet. Use an approved authenticated TLS
gateway and access-control policy for any remote deployment.

If an existing Sentinel bridge owns port 8090, the launcher reuses it only when
it is healthy and belongs to this workspace. Stop unknown processes rather than
starting a second bridge.

## Before opening a pull request

```powershell
python -m pytest -q
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile vision config
```

Run `git status` and confirm that no `.env`, camera-source file, evidence,
database content, logs, API keys, or captured imagery is staged.
