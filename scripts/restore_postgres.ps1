[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [Parameter(Mandatory = $true)]
    [switch]$ConfirmDatabaseReplacement,
    [string]$ComposeProject = ''
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmDatabaseReplacement) {
    throw 'Restore is destructive. Re-run with -ConfirmDatabaseReplacement after change approval.'
}
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
$remotePath = "/tmp/approved-restore-$suffix.dump"

try {
    & $docker cp $resolvedBackup "${containerId}:$remotePath"
    if ($LASTEXITCODE -ne 0) { throw 'docker cp failed.' }
    & $docker @composeArgs stop api
    & $docker @composeArgs exec -T postgis sh -ceu 'dropdb --if-exists --force -U "$POSTGRES_USER" "$POSTGRES_DB"; createdb -U "$POSTGRES_USER" "$POSTGRES_DB"; pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges "$1"' sentinel-restore $remotePath
    if ($LASTEXITCODE -ne 0) { throw 'Approved database restore failed.' }
    Write-Host 'Database restore completed. Start the API only after verification.'
}
finally {
    & $docker @composeArgs exec -T postgis rm -f -- $remotePath 2>$null
}
