[CmdletBinding()]
param(
    [string]$OutputPath = (Join-Path $PSScriptRoot 'sentinel-port-training-bundle.zip')
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ('sentinel-colab-' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $staging | Out-Null
    $bundleRoot = Join-Path $staging 'sentinel'
    New-Item -ItemType Directory -Path $bundleRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'training') -Destination $bundleRoot -Recurse
    Copy-Item -LiteralPath (Join-Path $projectRoot 'cloud_training') -Destination $bundleRoot -Recurse
    Remove-Item -LiteralPath (Join-Path $bundleRoot 'training\datasets') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $bundleRoot 'training\runs') -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $bundleRoot -Directory -Recurse -Filter '__pycache__' |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $bundleRoot 'cloud_training\sentinel-port-training-bundle.zip') -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $OutputPath) { Remove-Item -LiteralPath $OutputPath -Force }
    Compress-Archive -LiteralPath $bundleRoot -DestinationPath $OutputPath -CompressionLevel Optimal
    Write-Host "Created safe training-code bundle: $OutputPath" -ForegroundColor Green
    Write-Host 'It contains no .env, API keys, recordings, evidence, face data, or model weights.' -ForegroundColor Yellow
}
finally {
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
}
