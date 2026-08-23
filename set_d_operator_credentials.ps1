param(
    [string]$BackendRoot = 'D:\fpv'
)

$ErrorActionPreference = 'Stop'
$compose = Join-Path $BackendRoot 'docker-compose.yml'
$gpu = Join-Path $BackendRoot 'docker-compose.gpu.yml'
$face = Join-Path $BackendRoot 'docker-compose.face.yml'
$usersFile = Join-Path $BackendRoot 'secrets\auth-users.json'
if (-not (Test-Path -LiteralPath $compose)) { throw "Compose file missing: $compose" }
if (-not (Test-Path -LiteralPath $usersFile)) { throw "Operator file missing: $usersFile" }

$composeArgs = @('compose', '--project-directory', $BackendRoot, '-f', $compose)
if (Test-Path -LiteralPath $gpu) { $composeArgs += @('-f', $gpu) }
if (Test-Path -LiteralPath $face) { $composeArgs += @('-f', $face) }
$composeArgs += @('--profile', 'vision', '--profile', 'telemetry', '--profile', 'v2x')

# Fail before changing the local credential file when Docker Desktop's Linux
# engine is unavailable. Compose commands otherwise emit misleading errors
# much later in the update process.
$dockerEngine = & docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($dockerEngine | Select-Object -Last 1))) {
    throw 'Docker Desktop Linux engine is not running. Open Docker Desktop, wait for “Engine running”, then run this credential command again.'
}

$document = Get-Content -LiteralPath $usersFile -Raw | ConvertFrom-Json
$accounts = @($document.users | Where-Object { -not $_.disabled })
if ($accounts.Count -ne 1) {
    throw 'Credential manager requires exactly one active operator account.'
}
$record = $accounts[0]
$currentUsername = [string]$record.username
$enteredUsername = Read-Host "New username [$currentUsername]"
$newUsername = if ([string]::IsNullOrWhiteSpace($enteredUsername)) { $currentUsername } else { $enteredUsername.Trim() }
if ($newUsername -notmatch '^[A-Za-z][A-Za-z0-9._-]{2,31}$') {
    throw 'Username must be 3-32 characters, start with a letter, and use only letters, numbers, dot, underscore, or hyphen.'
}

function Read-PlainPassword([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

$first = Read-PlainPassword "New password for '$newUsername' (minimum 14 characters)"
$second = Read-PlainPassword 'Confirm password'
try {
    if ($first -cne $second) { throw 'Passwords do not match.' }
    if ($first.Length -lt 14) { throw "Password contains $($first.Length) characters; at least 14 are required." }
    $hashCode = "import sys; from argon2 import PasswordHasher; print(PasswordHasher().hash(sys.stdin.read().rstrip('\\r\\n')))"
    $hash = $first | & docker @composeArgs exec -T api python -c $hashCode
    if ($LASTEXITCODE -ne 0 -or -not $hash) { throw 'Password hashing inside the API container failed.' }
    $hash = ($hash | Select-Object -Last 1).Trim()

    $newDocument = [ordered]@{
        version = 1
        users = @(
            [ordered]@{
                username = $newUsername
                secret_hash = $hash
                roles = [string[]]@('operator')
                disabled = $false
            }
        )
    }
    [IO.File]::WriteAllText($usersFile, ($newDocument | ConvertTo-Json -Depth 8) + "`n", [Text.UTF8Encoding]::new($false))

    # Compose secrets are attached at container creation. Remove/recreate so the
    # API is guaranteed to mount the newly written credential file.
    & docker @composeArgs rm -sf api gateway
    if ($LASTEXITCODE -ne 0) { throw 'API/gateway removal before credential reload failed.' }
    & docker @composeArgs up -d api gateway
    if ($LASTEXITCODE -ne 0) { throw 'API/gateway recreation after credential update failed.' }

    $deadline = (Get-Date).AddMinutes(2)
    $ready = $false
    do {
        try {
            $response = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/readyz' -TimeoutSec 4
            $ready = [bool]$response
        } catch { $ready = $false }
        if (-not $ready) { Start-Sleep -Seconds 2 }
    } while (-not $ready -and (Get-Date) -lt $deadline)
    if (-not $ready) { throw 'API/gateway did not become ready after credential update.' }

    $mountedUserCode = "import json; print(json.load(open('/run/secrets/auth-users.json', encoding='utf-8'))['users'][0]['username'])"
    $mountedUser = & docker @composeArgs exec -T api python -c $mountedUserCode
    if ($LASTEXITCODE -ne 0 -or ($mountedUser | Select-Object -Last 1).Trim() -cne $newUsername) {
        throw 'API container did not mount the updated operator username.'
    }

    # Validate the exact password hash in the mounted secret.  The HTTP token
    # request below remains the authoritative full AuthManager check; using a
    # multi-line native-process probe here is fragile for valid passwords that
    # contain shell-sensitive characters.
    $mountedSecretCode = "import sys,json; from argon2 import PasswordHasher; p=sys.stdin.read().rstrip('\\r\\n'); u=json.load(open('/run/secrets/auth-users.json', encoding='utf-8'))['users'][0]; PasswordHasher().verify(u['secret_hash'], p); print('ok')"
    $mountedSecret = $first | & docker @composeArgs exec -T api python -c $mountedSecretCode
    if ($LASTEXITCODE -ne 0 -or ($mountedSecret | Select-Object -Last 1).Trim() -cne 'ok') {
        throw 'The updated password was not accepted by the API container. No login changes were completed.'
    }

    # Explicitly URL-encode the form values. This avoids Windows PowerShell
    # edge cases when a password contains characters such as &, +, or =.
    $formBody = "username=$([System.Net.WebUtility]::UrlEncode($newUsername))&password=$([System.Net.WebUtility]::UrlEncode($first))&grant_type=password"
    try {
        $token = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8080/api/auth/token' `
            -ContentType 'application/x-www-form-urlencoded' `
            -Body $formBody `
            -TimeoutSec 10
    } catch {
        $responseText = $_.Exception.Message
        if ($_.Exception.Response) {
            try {
                $reader = [IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
                $responseText = $reader.ReadToEnd()
                $reader.Dispose()
            } catch { }
        }
        throw "HTTP login verification failed after the API AuthManager accepted the credential. The service on 127.0.0.1:8080 may be stale. Response: $responseText"
    }
    if (-not $token.access_token) { throw 'Credential verification did not return an access token.' }
    Write-Host "Credentials verified. Sign in with username: $newUsername" -ForegroundColor Green
} finally {
    $first = $null
    $second = $null
    $hash = $null
    $token = $null
}
