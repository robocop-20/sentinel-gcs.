[CmdletBinding()]
param(
    [ValidateRange(1, 500)]
    [int]$Epochs = 100,

    [ValidateRange(320, 1920)]
    [int]$ImageSize = 960,

    [ValidateRange(1, 16)]
    [int]$Batch = 4
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSCommandPath
$docker = 'D:\Docker\Desktop\resources\bin\docker.exe'
$datasetRoot = Join-Path $projectRoot 'training\datasets\port'

if (-not (Test-Path -LiteralPath $docker -PathType Leaf)) {
    throw "Docker Desktop executable was not found at $docker"
}
if (-not (Test-Path -LiteralPath (Join-Path $datasetRoot 'images\train') -PathType Container)) {
    throw "Port training images are missing. Put labelled images and YOLO .txt labels under $datasetRoot before starting training."
}

$compose = @(
    'compose',
    '-f', (Join-Path $projectRoot 'docker-compose.yml'),
    '-f', (Join-Path $projectRoot 'docker-compose.gpu.yml'),
    '-f', (Join-Path $projectRoot 'docker-compose.training.gpu.yml'),
    '--profile', 'training'
)

Write-Host '1/4 Validating the local dataset...' -ForegroundColor Cyan
& $docker @compose 'run' '--rm' 'trainer' 'training/validate_port_dataset.py' '--report' 'training/runs/port-yolo11/dataset-validation.json'
if ($LASTEXITCODE -ne 0) { throw 'Dataset validation failed. Training was not started.' }

Write-Host '2/4 Training on GPU 0...' -ForegroundColor Cyan
& $docker @compose 'run' '--rm' 'trainer' 'training/train_port_model.py' `
    '--base-model' '/models/yolo11s.pt' '--device' '0' '--epochs' $Epochs '--imgsz' $ImageSize '--batch' $Batch
if ($LASTEXITCODE -ne 0) { throw 'Training failed. The current deployed model was not changed.' }

$candidate = 'training/runs/port-yolo11/weights/best.pt'
$evaluationReport = 'training/runs/port-yolo11/evaluation.json'
$benchmarkReport = 'training/runs/port-yolo11/inference-benchmark.json'
$calibrationReport = 'reports/vision/confidence-calibration.json'
$gateReport = 'training/runs/port-yolo11/release-gate.json'
Write-Host '3/4 Evaluating the held-out split...' -ForegroundColor Cyan
& $docker @compose 'run' '--rm' 'trainer' 'training/evaluate_port_model.py' `
    '--model' $candidate '--device' '0' '--imgsz' $ImageSize '--report' $evaluationReport
if ($LASTEXITCODE -ne 0) { throw 'Evaluation failed. The candidate model was not promoted.' }

Write-Host '4/4 Benchmarking single-frame GPU inference...' -ForegroundColor Cyan
& $docker @compose 'run' '--rm' 'trainer' 'training/benchmark_inference.py' `
    '--model' $candidate '--images' 'training/datasets/port/images/test' '--device' '0' '--imgsz' $ImageSize '--report' $benchmarkReport
if ($LASTEXITCODE -ne 0) { throw 'GPU benchmark failed. The candidate model was not promoted.' }

& $docker @compose 'run' '--rm' 'trainer' 'training/release_gate.py' `
    '--report' $evaluationReport '--latency-report' $benchmarkReport `
    '--calibration-report' $calibrationReport '--output' $gateReport
if ($LASTEXITCODE -ne 0) { throw 'The candidate did not meet the release thresholds and was not promoted.' }

Write-Host ''
Write-Host 'Training, held-out evaluation, and the deterministic release gate completed.' -ForegroundColor Green
Write-Host 'See PORT_FINE_TUNING.md for the required SHA-256 manifest and controlled promotion step.' -ForegroundColor Yellow
