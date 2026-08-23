param(
    [string[]]$EnvFiles = @(
        (Join-Path $PSScriptRoot '.env'),
        (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Downloads\fpv\.env')
    )
)

$ErrorActionPreference = 'Stop'
$secureKey = Read-Host 'Paste the NEW Gemini API key (input is hidden)' -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($key) -or $key.Length -lt 20) {
        throw 'The key was empty or unexpectedly short.'
    }
    foreach ($path in ($EnvFiles | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Environment file not found: $path"
        }
        $lines = [Collections.Generic.List[string]]::new()
        $lines.AddRange([string[]][IO.File]::ReadAllLines($path))
        $replacement = "GEMINI_API_KEY=$key"
        $index = -1
        for ($position = 0; $position -lt $lines.Count; $position++) {
            if ($lines[$position].StartsWith('GEMINI_API_KEY=')) {
                $index = $position
                break
            }
        }
        if ($index -ge 0) { $lines[$index] = $replacement } else { $lines.Add($replacement) }
        [IO.File]::WriteAllLines($path, $lines, [Text.UTF8Encoding]::new($false))
        Write-Host "Updated $path without displaying the key." -ForegroundColor Green
    }
}
finally {
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
    $key = $null
    $secureKey = $null
}

Write-Host 'Restart the API container, then run .\verify_backend.ps1 to confirm both LLM workers.'
