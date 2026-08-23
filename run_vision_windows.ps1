param(
    [string]$VideoSource = '',
    [int]$DeviceIndex = -1,
    [ValidateSet('auto', 'dshow', 'gstreamer')][string]$Backend = 'auto',
    [string]$ApiUrl = 'http://localhost:8080',
    [string]$ModelPath = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
. (Join-Path $projectRoot 'scripts\camera_source.ps1')

if (-not $VideoSource -and $DeviceIndex -ge 0) { $VideoSource = "$DeviceIndex" }
if (-not $VideoSource) {
    $VideoSource = Get-SentinelCameraSource -ProjectRoot $projectRoot
}
elseif ($DeviceIndex -lt 0 -and $Backend -ne 'gstreamer') {
    $VideoSource = ConvertTo-SentinelCameraSource -Source $VideoSource
}

$venv = Join-Path $projectRoot '.vision-venv'
if (-not (Test-Path $venv)) { python -m venv $venv }
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install --upgrade pip
# Explicit CPU wheels prevent a CUDA download on a non-NVIDIA Windows host.
& $python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
& $python -m pip install -r requirements-vision.txt

if (-not $ModelPath) {
    $modelDirectory = Join-Path $projectRoot 'models'
    New-Item -ItemType Directory -Path $modelDirectory -Force | Out-Null
    $ModelPath = Join-Path $modelDirectory 'yolo11s.pt'
}
$env:API_URL = $ApiUrl
$env:VIDEO_SOURCE = $VideoSource
$env:VIDEO_BACKEND = $Backend
$env:YOLO_MODEL = $ModelPath
& $python -m app.vision_worker
