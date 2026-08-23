[CmdletBinding()]
param(
    [switch]$NoBuild,
    [switch]$NoBrowser,
    [switch]$CpuVision,
    [switch]$WithTelemetry,
    [switch]$WithV2X,
    [switch]$ReplaceBridge
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Test-LocalPort {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connected = $client.ConnectAsync('127.0.0.1', $Port).Wait(350)
        return $connected -and $client.Connected
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Get-BridgeInstanceId {
    param([string]$ProjectPath)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($ProjectPath.ToLowerInvariant())
        $hash = $sha256.ComputeHash($bytes)
        return -join ($hash[0..7] | ForEach-Object { $_.ToString('x2') })
    }
    finally { $sha256.Dispose() }
}

function Get-ListeningProcessId {
    param([int]$Port)
    $line = netstat -ano -p tcp |
        Select-String ":$Port\s+.*LISTENING" |
        Select-Object -First 1
    if (-not $line) { return $null }
    $parts = $line.Line.Trim() -split '\s+'
    return [int]$parts[-1]
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw 'Docker CLI was not found. Start Docker Desktop, then run this launcher again.'
}
$dockerVersion = & $docker.Source info --format '{{.ServerVersion}}' 2>$null
if ($LASTEXITCODE -ne 0 -or -not $dockerVersion) {
    throw 'Docker Desktop is not ready or this account cannot access its engine. Start Docker Desktop, wait for Engine running, then retry.'
}

if (-not (Test-Path -LiteralPath 'config\camera-source.txt')) {
    throw 'Camera source is missing. Run set_camera_source.ps1 once, then retry.'
}

$requiredModels = @(
    'models\yolo11s.pt',
    'models\yolo11n-pose.pt',
    'models\face\yunet.onnx',
    'models\person-verifier\hub\checkpoints\fasterrcnn_mobilenet_v3_large_320_fpn-907ea3f9.pth'
)
$missingModels = @($requiredModels | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missingModels.Count) {
    throw "Required model files are missing: $($missingModels -join ', ')"
}

$expectedBridgeInstance = Get-BridgeInstanceId -ProjectPath $projectRoot
$startBridge = -not (Test-LocalPort -Port 8090)
if (-not $startBridge) {
    try {
        $bridgeHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8090/healthz' -TimeoutSec 2
    }
    catch {
        throw 'Port 8090 is occupied, but it is not a healthy Sentinel camera bridge. Stop the owning process and retry.'
    }
    if ($bridgeHealth.service -ne 'sentinel-mjpeg-bridge') {
        throw 'Port 8090 is not owned by Sentinel. The launcher will not terminate an unknown process.'
    }
    if ($bridgeHealth.instance_id -ne $expectedBridgeInstance) {
        if (-not $ReplaceBridge) {
            throw 'Port 8090 belongs to an older bridge. Re-run this launcher with -ReplaceBridge to perform the verified cutover.'
        }
        $bridgePid = Get-ListeningProcessId -Port 8090
        $bridgeProcess = if ($bridgePid) { Get-Process -Id $bridgePid -ErrorAction SilentlyContinue } else { $null }
        if (-not $bridgeProcess -or $bridgeProcess.ProcessName -ne 'python') {
            throw 'The verified bridge listener changed before replacement; refusing to terminate it.'
        }
        Write-Host "Stopping verified older Sentinel bridge (PID $bridgePid)..."
        Stop-Process -Id $bridgePid -ErrorAction Stop
        for ($attempt = 1; $attempt -le 20 -and (Test-LocalPort -Port 8090); $attempt++) {
            Start-Sleep -Milliseconds 100
        }
        if (Test-LocalPort -Port 8090) { throw 'Older bridge did not release port 8090.' }
        $startBridge = $true
    }
    else {
        Write-Host 'Matching camera bridge is already running.'
    }
}

if ($startBridge) {
    Write-Host 'Starting the authenticated camera bridge...'
    $bridgeArgs = @(
        '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', (Join-Path $projectRoot 'run_mjpeg_bridge_windows.ps1')
    )
    Start-Process -FilePath 'powershell.exe' -ArgumentList $bridgeArgs -WorkingDirectory $projectRoot -WindowStyle Hidden
    $bridgeReady = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $bridgeHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8090/healthz' -TimeoutSec 1
            if ($bridgeHealth.service -eq 'sentinel-mjpeg-bridge' -and $bridgeHealth.instance_id -eq $expectedBridgeInstance) {
                $bridgeReady = $true
                break
            }
        }
        catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $bridgeReady) { throw 'The current workspace camera bridge did not become ready.' }
}

$composeArgs = @('compose', '-f', 'docker-compose.yml')
$gpuAvailable = (-not $CpuVision) -and [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($gpuAvailable) {
    $composeArgs += @('-f', 'docker-compose.gpu.yml')
    Write-Host 'NVIDIA runtime detected; using the GPU vision profile.'
}
else {
    Write-Host 'Using the CPU vision profile. Pass no switch on an NVIDIA host to enable GPU automatically.'
}
$composeArgs += @('-f', 'docker-compose.face.yml')
$composeArgs += @('--profile', 'vision')
if ($WithTelemetry) { $composeArgs += @('--profile', 'telemetry') }
if ($WithV2X) { $composeArgs += @('--profile', 'v2x') }
$composeArgs += @('up', '-d', '--wait', '--wait-timeout', '180')
if (-not $NoBuild) { $composeArgs += '--build' }

Write-Host 'Starting Sentinel services...'
& $docker.Source @composeArgs
if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE." }

$ready = $false
for ($attempt = 1; $attempt -le 40; $attempt++) {
    try {
        $response = Invoke-RestMethod -Uri 'http://localhost:8080/readyz' -TimeoutSec 2
        if ($response) { $ready = $true; break }
    }
    catch { Start-Sleep -Milliseconds 750 }
}

if (-not $ready) {
    throw 'Services started, but readiness did not pass within 30 seconds. Run docker compose logs --tail 100 gateway api vision.'
}

Write-Host 'Sentinel is ready at http://localhost:8080/' -ForegroundColor Green
if (-not $NoBrowser) {
    Start-Process 'http://localhost:8080/'
}
