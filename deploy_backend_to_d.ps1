param(
    [string]$BackendRoot = 'D:\fpv',
    [switch]$CpuOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = [System.IO.Path]::GetFullPath($sourceRoot)
$BackendRoot = [System.IO.Path]::GetFullPath($BackendRoot)
if ($sourceRoot -eq $BackendRoot) { throw 'Source and backend roots must be different.' }
if (-not (Test-Path -LiteralPath $BackendRoot -PathType Container)) { throw "Backend root not found: $BackendRoot" }
if (-not (Test-Path -LiteralPath (Join-Path $BackendRoot 'models') -PathType Container)) { throw 'D: models directory is missing; deployment stopped.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is not available.' }

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running.' }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path (Split-Path -Parent $BackendRoot) "fpv-backups\$stamp"
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

$backupItems = @(
    'app', 'infra', 'db', 'scripts', 'secrets', '.env', '.dockerignore',
    'docker-compose.yml', 'docker-compose.face.yml', 'docker-compose.gpu.yml',
    'Dockerfile.api', 'Dockerfile.mqtt', 'Dockerfile.postgis',
    'Dockerfile.vision', 'Dockerfile.vision-face', 'Dockerfile.vision-gpu',
    'requirements-api.txt', 'requirements-face.txt', 'requirements-vision.txt'
)
foreach ($item in $backupItems) {
    $candidate = Join-Path $BackendRoot $item
    if (Test-Path -LiteralPath $candidate) {
        Copy-Item -LiteralPath $candidate -Destination $backupRoot -Recurse -Force
    }
}
Write-Host "D: backup created: $backupRoot" -ForegroundColor Cyan

# Backend code and infrastructure only. D owns models, evidence, camera source,
# .env, secrets/credentials, certificates, and Docker volumes. In particular,
# never replace D:\fpv\secrets during an application deployment: doing so would
# silently revert the live operator account and break console login.
foreach ($directory in @('app', 'infra', 'db', 'scripts')) {
    $source = Join-Path $sourceRoot $directory
    $destination = Join-Path $BackendRoot $directory
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Copy-Item -Path (Join-Path $source '*') -Destination $destination -Recurse -Force
}

$rootFiles = @(
    '.dockerignore', 'docker-compose.yml', 'docker-compose.face.yml',
    'docker-compose.gpu.yml', 'Dockerfile.api', 'Dockerfile.mqtt',
    'Dockerfile.postgis', 'Dockerfile.vision', 'Dockerfile.vision-face',
    'Dockerfile.vision-gpu', 'requirements-api.txt', 'requirements-face.txt',
    'requirements-vision.txt', 'index.html', 'styles.css', 'operations.css',
    'app.js', 'run_mjpeg_bridge_windows.ps1', 'run_vision_windows.ps1',
    'set_camera_source.ps1', 'verify_backend.ps1'
)
foreach ($file in $rootFiles) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $file) -Destination (Join-Path $BackendRoot $file) -Force
}

# Preserve every D value and append only settings that D does not yet define.
$sourceEnv = Join-Path $sourceRoot '.env'
$targetEnv = Join-Path $BackendRoot '.env'
if (-not (Test-Path -LiteralPath $targetEnv)) { throw "D environment file not found: $targetEnv" }
$targetLines = [System.Collections.Generic.List[string]]::new()
Get-Content -LiteralPath $targetEnv | ForEach-Object { [void]$targetLines.Add($_) }
$known = @{}
foreach ($line in $targetLines) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=') { $known[$matches[1]] = $true }
}
foreach ($line in (Get-Content -LiteralPath $sourceEnv)) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=' -and -not $known.ContainsKey($matches[1])) {
        [void]$targetLines.Add($line)
        $known[$matches[1]] = $true
    }
}
[System.IO.File]::WriteAllLines($targetEnv, $targetLines, [System.Text.UTF8Encoding]::new($false))

# The local signed V2X gateway emits authenticated heartbeats under its own
# source ID. Keep fail-closed validation while allowing that first known peer.
if (-not $known.ContainsKey('V2X_ALLOWED_SOURCES')) {
    [void]$targetLines.Add('V2X_ALLOWED_SOURCES=ground-station-01')
    [System.IO.File]::WriteAllLines($targetEnv, $targetLines, [System.Text.UTF8Encoding]::new($false))
}

$composeArgs = @('compose', '--project-directory', $BackendRoot, '-f', (Join-Path $BackendRoot 'docker-compose.yml'))
if (-not $CpuOnly) { $composeArgs += @('-f', (Join-Path $BackendRoot 'docker-compose.gpu.yml')) }
$composeArgs += @('-f', (Join-Path $BackendRoot 'docker-compose.face.yml'))
$composeArgs += @('--profile', 'vision', '--profile', 'telemetry', '--profile', 'v2x')

Write-Host 'Building and starting the consolidated D: production stack ...' -ForegroundColor Cyan
& docker @composeArgs up -d --build --remove-orphans
if ($LASTEXITCODE -ne 0) {
    $logPath = Join-Path $sourceRoot 'backend-deployment-failure.log'
    & docker @composeArgs ps -a 2>&1 | Set-Content -LiteralPath $logPath
    & docker @composeArgs logs --tail 300 mqtt api gateway postgis 2>&1 | Add-Content -LiteralPath $logPath
    throw "D: Compose deployment failed. Diagnostic log: $logPath; backup: $backupRoot"
}

$readyUrl = 'http://127.0.0.1:8080/readyz'
$deadline = (Get-Date).AddMinutes(5)
$ready = $null
do {
    try { $ready = Invoke-RestMethod -Uri $readyUrl -TimeoutSec 5 } catch {}
    if ($ready) { break }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)
if (-not $ready) {
    $logPath = Join-Path $sourceRoot 'backend-api-failure.log'
    & docker @composeArgs logs --tail 250 gateway api 2>&1 | Set-Content -LiteralPath $logPath
    throw "D backend remains unready. Diagnostic log: $logPath; backup: $backupRoot"
}

Write-Host 'D: backend deployment is ready.' -ForegroundColor Green
Write-Host 'Models: D:\fpv\models (preserved)'
Write-Host 'Camera IP: D:\fpv\config\camera-source.txt (preserved/dynamic)'
Write-Host "Backup: $backupRoot"

& (Join-Path $sourceRoot 'connect_c_frontend_to_d_backend.ps1') -BackendRoot $BackendRoot -NoBrowser
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:18082/' }
