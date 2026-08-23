Set-StrictMode -Version Latest

function ConvertTo-SentinelCameraSource {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source
    )

    $candidate = $Source.Trim()
    if (-not $candidate) {
        throw 'The camera source cannot be empty.'
    }

    # For the common IP Webcam case, allow the operator to enter only
    # 192.168.1.20 or 192.168.1.20:8080.
    if ($candidate -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
        if ($candidate -notmatch '^[a-zA-Z0-9.-]+(?::\d{1,5})?$') {
            throw "Camera source '$candidate' is not a valid host, host:port, or absolute URL."
        }
        if ($candidate -notmatch ':\d{1,5}$') {
            $candidate = "${candidate}:8080"
        }
        $candidate = "http://${candidate}/videofeed"
    }

    $uri = $null
    if (-not [System.Uri]::TryCreate($candidate, [System.UriKind]::Absolute, [ref]$uri)) {
        throw "Camera source '$candidate' is not a valid absolute URL."
    }
    if ($uri.Scheme -notin @('http', 'https', 'rtsp', 'rtsps')) {
        throw "Unsupported camera protocol '$($uri.Scheme)'. Use HTTP(S) or RTSP(S)."
    }
    if (-not $uri.Host) {
        throw 'The camera source must include a host name or IP address.'
    }
    if ($uri.Port -lt 1 -or $uri.Port -gt 65535) {
        throw "Camera port '$($uri.Port)' is outside the valid range 1-65535."
    }

    return $uri.AbsoluteUri
}

function Get-SentinelCameraSource {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $sourcePath = Get-SentinelCameraSourcePath -ProjectRoot $ProjectRoot
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Camera source file not found: $sourcePath. Run .\set_camera_source.ps1 -Source <camera-ip-or-url>."
    }

    $source = Get-Content -LiteralPath $sourcePath |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith('#') } |
        Select-Object -First 1
    if (-not $source) {
        throw "Camera source file is empty: $sourcePath. Run .\set_camera_source.ps1 -Source <camera-ip-or-url>."
    }

    return ConvertTo-SentinelCameraSource -Source $source
}

function Get-SentinelCameraSourcePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    return Join-Path $ProjectRoot 'config\camera-source.txt'
}
