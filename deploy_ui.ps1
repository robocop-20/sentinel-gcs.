[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
throw @'
Direct deployment is disabled in this development workspace.
No files were copied and D:\fpv was not accessed.
Follow docs\DEPLOYMENT_AND_CUTOVER.md only during an approved future change window.
'@
