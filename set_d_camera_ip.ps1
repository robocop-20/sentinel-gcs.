param(
    [Parameter(Mandatory = $true, Position = 0)]
    [Alias('Ip', 'Url')]
    [string]$Source,
    [string]$BackendRoot = 'D:\fpv'
)

$ErrorActionPreference = 'Stop'
$setter = Join-Path $BackendRoot 'set_camera_source.ps1'
$bridge = Join-Path $BackendRoot 'run_mjpeg_bridge_windows.ps1'
if (-not (Test-Path -LiteralPath $setter)) { throw "Camera setter not found: $setter" }
if (-not (Test-Path -LiteralPath $bridge)) { throw "Camera bridge not found: $bridge" }

& $setter -Source $Source

# Keep the informational .env value aligned for operators inspecting the D:
# stack, but the camera-source file above remains the single authoritative
# input. Vision consumes the token-protected local bridge rather than a
# second direct phone URL.
$environmentFile = Join-Path $BackendRoot '.env'
if (Test-Path -LiteralPath $environmentFile) {
    $configuredSource = Get-Content -LiteralPath (Join-Path $BackendRoot 'config\camera-source.txt') | Select-Object -First 1
    $environmentLines = [System.Collections.Generic.List[string]]::new()
    Get-Content -LiteralPath $environmentFile | ForEach-Object { [void]$environmentLines.Add($_) }
    $updated = $false
    for ($index = 0; $index -lt $environmentLines.Count; $index++) {
        if ($environmentLines[$index] -match '^VIDEO_SOURCE=') {
            $environmentLines[$index] = "VIDEO_SOURCE=$configuredSource"
            $updated = $true
            break
        }
    }
    if (-not $updated) { [void]$environmentLines.Add("VIDEO_SOURCE=$configuredSource") }
    [IO.File]::WriteAllLines($environmentFile, $environmentLines, [Text.UTF8Encoding]::new($false))
}

$listeners = @(Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -match 'app\.mjpeg_bridge') {
        Stop-Process -Id $listener.OwningProcess -Force
        Wait-Process -Id $listener.OwningProcess -Timeout 10 -ErrorAction SilentlyContinue
    } elseif ($process) {
        throw "Port 8090 is owned by an unrelated process (PID $($listener.OwningProcess)); it was not stopped."
    }
}

Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $bridge
) -WorkingDirectory $BackendRoot -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds(15)
do {
    $active = Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue
    if ($active) { break }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
if (-not $active) { throw 'The D: camera bridge did not reopen port 8090.' }

$configured = Get-Content -LiteralPath (Join-Path $BackendRoot 'config\camera-source.txt') | Select-Object -First 1
Write-Host "Camera source active: $configured" -ForegroundColor Green
Write-Host 'Only configuration file: D:\fpv\config\camera-source.txt'
