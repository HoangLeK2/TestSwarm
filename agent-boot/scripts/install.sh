#!/usr/bin/env bash
# Install agent-boot on macOS / Linux (customer machine).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing: $1" >&2
    return 1
  fi
}

echo "== agent-boot install =="

if ! need_cmd adb; then
  echo "Install Android platform-tools (adb) first."
  echo "  macOS:  brew install android-platform-tools"
  echo "  Debian: sudo apt install adb"
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  [[ -f "$HOME/.local/bin/env" ]] && source "$HOME/.local/bin/env"
fi

need_cmd uv

uv sync --frozen --no-dev

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit RELAY_SERVER, RELAY_API_KEY, RELAY_ENROLLMENT_TOKEN"
else
  echo ".env already exists — not overwritten"
fi

echo ""
echo "Done. Next:"
echo "  adb devices"
if [[ "$(uname -s)" == "Linux" ]]; then
  echo "  ./scripts/run.sh              # keep host awake + relay (recommended on Linux)"
fi
echo "  uv run main.py --relay-only"
