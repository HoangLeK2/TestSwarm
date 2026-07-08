# Host runs ADB (USB/Wi-Fi devices); container is ADB client via host.docker.internal:5037.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArgs
)

$ErrorActionPreference = 'Stop'
# Avoid interactive Confirm spam from NetTCPIP / CIM cmdlets on some Windows setups.
$ConfirmPreference = 'None'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$AgentBootVersion = if ($env:AGENT_BOOT_VERSION) { $env:AGENT_BOOT_VERSION } else { '0.1.0' }
$Image = "agent-boot:$AgentBootVersion"
$AdbPort = if ($env:ADB_PORT) { [int]$env:ADB_PORT } else { 5037 }

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-AdbPortListening {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue -Confirm:$false
    return [bool]$conn
}

function Test-AdbServerGlobal {
    param([int]$Port)
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue -Confirm:$false
    foreach ($l in $listeners) {
        if ($l.LocalAddress -in @('0.0.0.0', '::', '[::]')) {
            return $true
        }
    }
    return $false
}

function Start-GlobalAdbServer {
    param([int]$Port)
    Write-Host "== Starting host ADB server (global 0.0.0.0:$Port, flag -a) =="
    adb kill-server 2>$null
    $log = Join-Path $env:TEMP 'agent-boot-adb-server.log'
    Start-Process -FilePath 'adb' -ArgumentList @('-a', '-P', "$Port", 'nodaemon', 'server') `
        -RedirectStandardOutput $log -RedirectStandardError $log -WindowStyle Hidden
    Start-Sleep -Seconds 2
    if (-not (Test-AdbPortListening -Port $Port)) {
        throw "ADB server did not start; see $log"
    }
    if (-not (Test-AdbServerGlobal -Port $Port)) {
        throw "ADB is up but not listening globally. Run: adb kill-server; adb -a -P $Port nodaemon server"
    }
}

if (-not (Test-Command adb)) {
    throw 'missing command: adb (install Android SDK Platform-Tools and add to PATH)'
}
if (-not (Test-Command docker)) {
    throw 'missing command: docker (install Docker Desktop)'
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker daemon is not running. Start Docker Desktop, then retry.'
}

docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'docker compose (v2) is required'
}

docker image inspect $Image *> $null
if ($LASTEXITCODE -ne 0) {
    throw "image $Image not found. Run: scripts\docker-load.cmd"
}

if (Test-AdbPortListening -Port $AdbPort) {
    if (Test-AdbServerGlobal -Port $AdbPort) {
        Write-Host "== ADB server already listening globally on port $AdbPort =="
    } else {
        Write-Warning "ADB on :$AdbPort is localhost-only; restarting with -a (global)"
        Start-GlobalAdbServer -Port $AdbPort
    }
} else {
    Start-GlobalAdbServer -Port $AdbPort
}

Write-Host '== Host devices =='
adb -P $AdbPort devices

$Subcommands = @('up', 'run', 'build', 'down', 'ps', 'logs', 'exec', 'pull', 'stop', 'restart', 'config')
if ($ComposeArgs.Count -eq 0) {
    $ComposeArgs = @('up', '-d')
} elseif ($ComposeArgs[0] -notin $Subcommands) {
    $ComposeArgs = @('up') + $ComposeArgs
}

Write-Host "== docker compose $($ComposeArgs -join ' ') =="
& docker compose @ComposeArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
