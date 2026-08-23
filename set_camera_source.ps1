param(
    [Parameter(Position = 0)]
    [Alias('Ip', 'Url')]
    [string]$Source
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $projectRoot 'scripts\camera_source.ps1')

if (-not $Source) {
    $Source = Read-Host 'Camera IP, IP:port, or complete stream URL'
}
$normalizedSource = ConvertTo-SentinelCameraSource -Source $Source
$configDirectory = Join-Path $projectRoot 'config'
$sourcePath = Get-SentinelCameraSourcePath -ProjectRoot $projectRoot
New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null

# Write a complete file in the same directory, then replace the active setting.
# The running bridge watches this file and never observes a partially typed URL.
$temporaryPath = Join-Path $configDirectory ('.camera-source.{0}.tmp' -f [guid]::NewGuid().ToString('N'))
try {
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporaryPath, "$normalizedSource`r`n", $utf8WithoutBom)
    Move-Item -LiteralPath $temporaryPath -Destination $sourcePath -Force
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}

Write-Host "Camera source updated: $normalizedSource" -ForegroundColor Green
Write-Host "Single configuration file: $sourcePath"
Write-Host 'The running MJPEG bridge will reload it automatically; no Docker rebuild is needed.'
