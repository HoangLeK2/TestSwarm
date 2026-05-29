# Install agent-boot on Windows (customer machine).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "== agent-boot install =="

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    Write-Error "adb not found. Install Android SDK Platform-Tools and add adb to PATH."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

uv sync --frozen --no-dev

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env — edit RELAY_SERVER, RELAY_API_KEY, RELAY_ENROLLMENT_TOKEN"
} else {
    Write-Host ".env already exists — not overwritten"
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  adb devices"
Write-Host "  uv run main.py --relay-only"
