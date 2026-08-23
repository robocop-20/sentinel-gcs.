[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
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
$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
$hashPath = "$resolvedBackup.sha256"
if (-not (Test-Path -LiteralPath $hashPath)) { throw "Missing checksum: $hashPath" }
$expectedHash = ((Get-Content -LiteralPath $hashPath -Raw).Trim() -split '\s+')[0]
$actualHash = (Get-FileHash -LiteralPath $resolvedBackup -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) { throw 'Backup checksum verification failed.' }

$composeArgs = @('compose')
if ($ComposeProject) { $composeArgs += @('-p', $ComposeProject) }
$containerId = (& $docker @composeArgs ps -q postgis).Trim()
if (-not $containerId) { throw 'PostGIS container is not running.' }

$suffix = [Guid]::NewGuid().ToString('N').Substring(0, 12)
$validationDatabase = "sentinel_restore_$suffix"
$remotePath = "/tmp/restore-$suffix.dump"

try {
    & $docker cp $resolvedBackup "${containerId}:$remotePath"
    if ($LASTEXITCODE -ne 0) { throw 'docker cp failed.' }
    & $docker @composeArgs exec -T postgis sh -ceu 'createdb -U "$POSTGRES_USER" "$1"' sentinel-restore $validationDatabase
    if ($LASTEXITCODE -ne 0) { throw 'Validation database creation failed.' }
    & $docker @composeArgs exec -T postgis sh -ceu 'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --no-privileges "$2"' sentinel-restore $validationDatabase $remotePath
    if ($LASTEXITCODE -ne 0) { throw 'Restore validation failed.' }
    & $docker @composeArgs exec -T postgis sh -ceu 'psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) AS events FROM events;" -c "SELECT COUNT(*) AS tracks FROM tracks;" -c "SELECT COUNT(*) AS audit_entries FROM audit_log;"' sentinel-restore $validationDatabase
    if ($LASTEXITCODE -ne 0) { throw 'Restored schema verification failed.' }
    Write-Host "Restore test passed in isolated database: $validationDatabase"
}
finally {
    & $docker @composeArgs exec -T postgis sh -c 'dropdb --if-exists --force -U "$POSTGRES_USER" "$1"' sentinel-restore $validationDatabase 2>$null
    & $docker @composeArgs exec -T postgis rm -f -- $remotePath 2>$null
}
