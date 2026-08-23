param(
    [string]$BackendRoot = 'D:\fpv'
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $scriptRoot 'set_d_operator_credentials.ps1') -BackendRoot $BackendRoot
