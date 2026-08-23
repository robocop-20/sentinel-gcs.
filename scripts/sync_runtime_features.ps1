[CmdletBinding()]
param(
    [string[]]$EnvironmentFiles = @(
        'C:\Users\ASUS\Downloads\fpv\.env'
    )
)

$ErrorActionPreference = 'Stop'

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Value
    )
    $lines = if (Test-Path -LiteralPath $Path) { @(Get-Content -LiteralPath $Path) } else { @() }
    $prefix = "$Name="
    $filtered = @($lines | Where-Object { -not $_.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) })
    $filtered += "$Name=$Value"
    # VS Code and Docker Desktop may keep a shared read handle open. Write with
    # FileShare.ReadWrite so normal tooling does not block deterministic config
    # normalisation. The complete file is still rewritten synchronously.
    $encoding = [System.Text.UTF8Encoding]::new($false)
    $stream = [System.IO.FileStream]::new(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        $stream.SetLength(0)
        $writer = [System.IO.StreamWriter]::new($stream, $encoding)
        try {
            foreach ($line in $filtered) { $writer.WriteLine($line) }
            $writer.Flush()
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

$features = [ordered]@{
    ENABLE_FACE_DETECTION = 'true'
    FACE_DETECTOR_MODEL_PATH = '/models/face/yunet.onnx'
    ENABLE_FALL_DETECTION = 'true'
    FALL_POSE_MODEL_PATH = '/models/yolo11n-pose.pt'
    FALL_POSE_IMG_SIZE = '320'
    FALL_POSE_INTERVAL = '2'
    FALL_POSE_CONFIDENCE = '0.45'
    FALL_MIN_CONFIDENCE = '0.68'
    FALL_MIN_SUSTAINED_FRAMES = '3'
    ENABLE_LLM_VERIFICATION = 'true'
    ENABLE_LLM_DETECTION_ADVISORY = 'true'
    ENABLE_EXTERNAL_LLM_EGRESS = 'true'
    ENABLE_EVIDENCE_CAPTURE = 'true'
    ENABLE_LLM_SECURITY_ADVISORY = 'true'
    ENABLE_EXTERNAL_LLM_TEXT_EGRESS = 'true'
}

foreach ($environmentFile in $EnvironmentFiles) {
    if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
        throw "Environment file was not found: $environmentFile"
    }
    foreach ($entry in $features.GetEnumerator()) {
        Set-DotEnvValue -Path $environmentFile -Name $entry.Key -Value $entry.Value
    }
    Write-Host "Runtime feature flags normalised: $environmentFile" -ForegroundColor Green
}

Write-Host 'Provider and API-key values were preserved. OpenRouter still requires its own local key.' -ForegroundColor Yellow
