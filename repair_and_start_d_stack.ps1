param(
    [string]$BackendRoot = 'D:\fpv',
    [string]$V2XAllowedSources = 'ground-station-01',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$frontendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$environmentFile = Join-Path $BackendRoot '.env'
$cameraFile = Join-Path $BackendRoot 'config\camera-source.txt'
$compose = Join-Path $BackendRoot 'docker-compose.yml'
$gpu = Join-Path $BackendRoot 'docker-compose.gpu.yml'
$face = Join-Path $BackendRoot 'docker-compose.face.yml'
foreach ($required in @($environmentFile, $cameraFile, $compose, $gpu, $face)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required D: file missing: $required" }
}

# Apply the reviewed gateway/runtime corrections to D before starting. Models,
# environment values, evidence, camera configuration, and volumes are untouched.
Copy-Item -LiteralPath (Join-Path $frontendRoot 'docker-compose.yml') -Destination $compose -Force
Copy-Item -LiteralPath (Join-Path $frontendRoot 'infra\nginx.conf') -Destination (Join-Path $BackendRoot 'infra\nginx.conf') -Force

function Set-EnvironmentValue([string]$Name, [string]$Value) {
    $lines = [System.Collections.Generic.List[string]]::new()
    Get-Content -LiteralPath $environmentFile | ForEach-Object { [void]$lines.Add($_) }
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^\s*$([regex]::Escape($Name))=") {
            $lines[$index] = "$Name=$Value"
            $found = $true
            break
        }
    }
    if (-not $found) { [void]$lines.Add("$Name=$Value") }
    [IO.File]::WriteAllLines($environmentFile, $lines, [Text.UTF8Encoding]::new($false))
}

Set-EnvironmentValue -Name 'V2X_ALLOWED_SOURCES' -Value $V2XAllowedSources

$camera = Get-Content -LiteralPath $cameraFile |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    Select-Object -First 1
if (-not $camera) { throw "Camera source is empty: $cameraFile" }
& (Join-Path $frontendRoot 'set_d_camera_ip.ps1') -Source $camera -BackendRoot $BackendRoot

$arguments = @(
    'compose', '--project-directory', $BackendRoot,
    '-f', $compose, '-f', $gpu, '-f', $face,
    '--profile', 'vision', '--profile', 'telemetry', '--profile', 'v2x'
)

Write-Host 'Starting D: infrastructure and API ...' -ForegroundColor Cyan
& docker @arguments up -d mqtt postgis api gateway evidence-retention
if ($LASTEXITCODE -ne 0) { throw 'D infrastructure/API startup failed.' }

$readyUrl = 'http://127.0.0.1:8080/readyz'
$deadline = (Get-Date).AddMinutes(3)
$ready = $null
do {
    try { $ready = Invoke-RestMethod -Uri $readyUrl -TimeoutSec 5 } catch {}
    if ($ready) { break }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)
if (-not $ready) {
    & (Join-Path $frontendRoot 'diagnose_d_stack.ps1') -BackendRoot $BackendRoot
    throw 'API did not become ready; diagnostic log was refreshed.'
}

Write-Host 'Starting GPU vision/models, telemetry, and V2X ...' -ForegroundColor Cyan
& docker @arguments up -d vision telemetry v2x
if ($LASTEXITCODE -ne 0) {
    & (Join-Path $frontendRoot 'diagnose_d_stack.ps1') -BackendRoot $BackendRoot
    throw 'Vision/model startup failed; diagnostic log was refreshed.'
}

& (Join-Path $frontendRoot 'connect_c_frontend_to_d_backend.ps1') -BackendRoot $BackendRoot -NoBrowser
Write-Host ''
Write-Host 'SENTINEL STARTED' -ForegroundColor Green
Write-Host "Camera source: $camera"
Write-Host 'Models: D:\fpv\models'
Write-Host 'Console: http://127.0.0.1:18082/'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:18082/' }
