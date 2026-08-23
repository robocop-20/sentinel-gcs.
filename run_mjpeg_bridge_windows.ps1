param(
    [string]$SourceUrl = '',
    [int]$ListenPort = 8090,
    [string]$Token = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
. (Join-Path $projectRoot 'scripts\camera_source.ps1')

$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $rootBytes = [System.Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())
    $rootHash = $sha256.ComputeHash($rootBytes)
    $bridgeInstanceId = -join ($rootHash[0..7] | ForEach-Object { $_.ToString('x2') })
}
finally { $sha256.Dispose() }

if (-not $SourceUrl) {
    $SourceUrl = Get-SentinelCameraSource -ProjectRoot $projectRoot
    $env:MJPEG_SOURCE_FILE = Get-SentinelCameraSourcePath -ProjectRoot $projectRoot
}
else {
    $SourceUrl = ConvertTo-SentinelCameraSource -Source $SourceUrl
    # An explicit launch override remains fixed for this bridge process.
    $env:MJPEG_SOURCE_FILE = ''
}
if (-not $Token) {
    $line = Select-String -LiteralPath '.env' -Pattern '^MJPEG_BRIDGE_TOKEN=' | Select-Object -First 1
    if ($line) { $Token = $line.Line.Substring('MJPEG_BRIDGE_TOKEN='.Length) }
}
if (-not $Token) { throw 'Provide -Token or set MJPEG_BRIDGE_TOKEN in .env.' }

$env:MJPEG_SOURCE_URL = $SourceUrl
$env:MJPEG_LISTEN_HOST = '0.0.0.0'
$env:MJPEG_LISTEN_PORT = "$ListenPort"
$env:MJPEG_BRIDGE_TOKEN = $Token
$env:MJPEG_BRIDGE_INSTANCE_ID = $bridgeInstanceId

try {
    $existing = Invoke-RestMethod -Uri "http://127.0.0.1:$ListenPort/healthz" -TimeoutSec 1
    if ($existing.service -eq 'sentinel-mjpeg-bridge' -and $existing.instance_id -eq $bridgeInstanceId) {
        Write-Host "Matching MJPEG bridge is already running on port $ListenPort." -ForegroundColor Green
        exit 0
    }
    throw "Port $ListenPort is owned by another bridge or process. Stop the older D:\fpv bridge before starting this workspace."
}
catch {
    if ($_.Exception.Message -like 'Port * is owned by another bridge*') { throw }
}
python -m app.mjpeg_bridge
