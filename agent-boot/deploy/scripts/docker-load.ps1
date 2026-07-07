# Load the agent-boot image tar matching this machine's CPU (amd64 or arm64).
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Get-HostArch {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        'AMD64' { return 'amd64' }
        'ARM64' { return 'arm64' }
        default {
            throw "unsupported host CPU '$($env:PROCESSOR_ARCHITECTURE)' (need AMD64 or ARM64)"
        }
    }
}

$Arch = Get-HostArch
$ArchTars = @(Get-ChildItem -File -Path $Root -Filter "agent-boot-image-*-$Arch.tar.gz")
if ($ArchTars.Count -eq 0) {
    $ArchTars = @(Get-ChildItem -File -Path $Root -Filter "agent-boot-image-*-$Arch.tar")
}
if ($ArchTars.Count -gt 1) {
    throw "multiple image tars for ${Arch}: $($ArchTars.Name -join ', ')"
}
if ($ArchTars.Count -eq 0) {
    $Legacy = @(Get-ChildItem -File -Path $Root -Filter 'agent-boot-image-*.tar.gz' |
        Where-Object { $_.Name -notmatch '-(amd64|arm64)\.tar' })
    if ($Legacy.Count -eq 1) {
        Write-Warning 'legacy single-arch bundle; may fail on wrong CPU'
        $Tar = $Legacy[0]
    } else {
        throw "no image tar for ${Arch} in $Root (expected agent-boot-image-VERSION-${Arch}.tar.gz)"
    }
} else {
    $Tar = $ArchTars[0]
}

Write-Host "== host arch: $Arch =="
Write-Host "== docker load: $($Tar.Name) =="

if ($Tar.Extension -eq '.gz' -or $Tar.Name -like '*.tar.gz') {
    $TempTar = Join-Path $env:TEMP "agent-boot-image-$Arch.tar"
    try {
        $InputStream = [System.IO.File]::OpenRead($Tar.FullName)
        $Gzip = New-Object System.IO.Compression.GZipStream(
            $InputStream,
            [System.IO.Compression.CompressionMode]::Decompress)
        $OutputStream = [System.IO.File]::Create($TempTar)
        $Gzip.CopyTo($OutputStream)
        $OutputStream.Close()
        $Gzip.Close()
        $InputStream.Close()
        docker load -i $TempTar
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        if (Test-Path $TempTar) { Remove-Item -Force $TempTar }
    }
} else {
    docker load -i $Tar.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ''
Write-Host 'Next: copy .env.example .env, then scripts\docker-up.cmd up -d'
