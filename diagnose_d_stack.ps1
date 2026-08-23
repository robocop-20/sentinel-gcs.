param([string]$BackendRoot = 'D:\fpv')

$ErrorActionPreference = 'Stop'
$frontendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$compose = Join-Path $BackendRoot 'docker-compose.yml'
$gpu = Join-Path $BackendRoot 'docker-compose.gpu.yml'
$face = Join-Path $BackendRoot 'docker-compose.face.yml'
$output = Join-Path $frontendRoot 'backend-deployment-failure.log'
if (-not (Test-Path -LiteralPath $compose)) { throw "Compose file not found: $compose" }

$arguments = @('compose', '--project-directory', $BackendRoot, '-f', $compose)
if (Test-Path -LiteralPath $gpu) { $arguments += @('-f', $gpu) }
if (Test-Path -LiteralPath $face) { $arguments += @('-f', $face) }
$arguments += @('--profile', 'vision', '--profile', 'telemetry', '--profile', 'v2x')

& docker @arguments ps -a 2>&1 | Set-Content -LiteralPath $output
& docker @arguments logs --tail 400 mqtt api gateway postgis evidence-retention vision telemetry v2x 2>&1 | Add-Content -LiteralPath $output
Write-Host "Diagnostic captured: $output" -ForegroundColor Green
Get-Content -LiteralPath $output
