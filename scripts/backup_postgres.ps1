[CmdletBinding()]
param(
    [string]$OutputDirectory = '',
    [string]$ComposeProject = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$docker = if ($dockerCommand) { $dockerCommand.Source } else { 'D:\Docker\Desktop\resources\bin\docker.exe' }
if (-not (Test-Path -LiteralPath $docker) -and -not $dockerCommand) {
    throw 'Docker CLI was not found in PATH or the configured Docker Desktop location.'
}

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot 'backups'
}
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null

$composeArgs = @('compose')
if ($ComposeProject) { $composeArgs += @('-p', $ComposeProject) }
$containerId = (& $docker @composeArgs ps -q postgis).Trim()
if (-not $containerId) { throw 'PostGIS container is not running.' }

$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupName = "sentinel-$timestamp.dump"
$backupPath = Join-Path $resolvedOutput $backupName
$remotePath = "/tmp/$backupName"

try {
    & $docker @composeArgs exec -T postgis sh -ceu 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges -f "$1"' sentinel-backup $remotePath
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed.' }
    & $docker cp "${containerId}:$remotePath" $backupPath
    if ($LASTEXITCODE -ne 0) { throw 'docker cp failed.' }

    $hash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$backupPath.sha256" -Value "$hash  $backupName" -Encoding ASCII
    [ordered]@{
        created_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        file = $backupName
        sha256 = $hash
        format = 'PostgreSQL custom archive'
        restore_test_required = $true
    } | ConvertTo-Json | Set-Content -LiteralPath "$backupPath.json" -Encoding UTF8
    Write-Host "Backup created: $backupPath"
    Write-Host "SHA-256: $hash"
}
finally {
    & $docker @composeArgs exec -T postgis rm -f -- $remotePath 2>$null
}
