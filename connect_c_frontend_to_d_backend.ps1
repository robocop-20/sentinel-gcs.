param(
    [string]$BackendRoot = 'D:\fpv',
    [string]$BackendUrl = 'http://127.0.0.1:8080',
    [int]$FrontendPort = 18082,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$frontendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeFile = Join-Path $BackendRoot 'docker-compose.yml'
$serverScript = Join-Path $frontendRoot 'scripts\connected_frontend_server.py'
$frontendUrl = "http://127.0.0.1:$FrontendPort"

if (-not (Test-Path -LiteralPath $composeFile)) { throw "Backend compose file not found: $composeFile" }
if (-not (Test-Path -LiteralPath $serverScript)) { throw "Connected frontend server not found: $serverScript" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is not available in PATH.' }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python is not available in PATH.' }

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running.' }

$backendReady = "$BackendUrl/readyz"
function Wait-BackendReady([int]$Seconds) {
    $until = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $result = Invoke-RestMethod -Uri $backendReady -TimeoutSec 3
            if ($result) { return $result }
        } catch {}
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $until)
    return $null
}

$ready = Wait-BackendReady -Seconds 4
if (-not $ready) {
    Write-Host 'D: API is not ready; restarting its existing container ...' -ForegroundColor Yellow
    docker compose --project-directory $BackendRoot -f $composeFile restart api
    if ($LASTEXITCODE -ne 0) { throw 'The D: backend API could not be restarted.' }
    $ready = Wait-BackendReady -Seconds 45
}
if (-not $ready) {
    Write-Host 'Restart was insufficient; rebuilding only the D: API image ...' -ForegroundColor Yellow
    docker compose --project-directory $BackendRoot -f $composeFile up -d --build api
    if ($LASTEXITCODE -ne 0) { throw 'The D: backend API rebuild failed.' }
    $ready = Wait-BackendReady -Seconds 180
}
if (-not $ready) {
    $logPath = Join-Path $frontendRoot 'backend-api-failure.log'
    docker compose --project-directory $BackendRoot -f $composeFile logs --tail 150 api 2>&1 | Set-Content -LiteralPath $logPath
    throw "Backend did not become ready. Diagnostic log saved to $logPath"
}

$existingFrontend = $null
try { $existingFrontend = Invoke-RestMethod -Uri "$frontendUrl/healthz" -TimeoutSec 2 } catch {}
if ($existingFrontend) {
    if ($existingFrontend.service -ne 'sentinel-connected-frontend' -or $existingFrontend.backend -ne $BackendUrl) {
        throw "Port $FrontendPort is occupied by a different service. Stop it or choose -FrontendPort." 
    }
} else {
    $arguments = @($serverScript, '--backend', $BackendUrl, '--port', "$FrontendPort")
    Start-Process -FilePath 'python' -ArgumentList $arguments -WorkingDirectory $frontendRoot -WindowStyle Hidden
    $frontendDeadline = (Get-Date).AddSeconds(20)
    do {
        try { $existingFrontend = Invoke-RestMethod -Uri "$frontendUrl/healthz" -TimeoutSec 2 } catch {}
        if ($existingFrontend) { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $frontendDeadline)
    if (-not $existingFrontend) { throw "Frontend did not start at $frontendUrl" }
}

Write-Host ''
Write-Host 'CONNECTED DEPLOYMENT READY' -ForegroundColor Green
Write-Host "  Frontend: $frontendUrl (C:)"
Write-Host "  Backend:  $BackendUrl (D:)"
Write-Host '  Camera bridge: existing D: bridge on port 8090 (no duplicate started)'
Write-Host '  REST:     same-origin proxy (no D: CORS changes required)'
if (-not $NoBrowser) { Start-Process $frontendUrl }
