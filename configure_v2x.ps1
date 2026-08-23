param(
    [string]$SourceId = 'ground-station-01'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw "Missing environment file: $envPath"
}

$values = [ordered]@{
    ENABLE_V2X = 'true'
    V2X_SOURCE_ID = $SourceId
    V2X_EVENTS_TOPIC = 'sentinel/v2x/events'
    V2X_HEARTBEATS_TOPIC = 'sentinel/v2x/heartbeats'
    V2X_MAX_AGE_S = '30'
    V2X_HEARTBEAT_INTERVAL_S = '5'
    V2X_DEVICE_OFFLINE_S = '15'
}

$lines = [System.Collections.Generic.List[string]]::new()
foreach ($line in Get-Content -LiteralPath $envPath) { $lines.Add($line) }
$secretLine = $lines | Where-Object { $_ -match '^V2X_SHARED_SECRET=' } | Select-Object -First 1
$secret = if ($secretLine) { $secretLine.Substring('V2X_SHARED_SECRET='.Length).Trim() } else { '' }
if (-not $secret) {
    $bytes = [byte[]]::new(32)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    $secret = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}
$values.V2X_SHARED_SECRET = $secret

foreach ($entry in $values.GetEnumerator()) {
    $prefix = "$($entry.Key)="
    $index = -1
    for ($position = 0; $position -lt $lines.Count; $position++) {
        if ($lines[$position].StartsWith($prefix, [StringComparison]::Ordinal)) { $index = $position; break }
    }
    $replacement = "$prefix$($entry.Value)"
    if ($index -ge 0) { $lines[$index] = $replacement } else { $lines.Add($replacement) }
}

[System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
Write-Host "V2X enabled for $SourceId. The secret was stored locally and was not printed." -ForegroundColor Green
Write-Host 'Development transport remains local-only until production mTLS certificates are provisioned.'
