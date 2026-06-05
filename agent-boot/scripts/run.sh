#!/usr/bin/env bash
# Run agent-boot on a Linux farm host without the machine suspending/shutting down.
#
# On Linux: starts keep-awake in the background, then runs main.py in the foreground.
# On macOS: runs main.py only (no keep-awake needed).
#
# Usage:
#   ./scripts/run.sh                    # keep-awake + uv run main.py --relay-only
#   ./scripts/run.sh --bootstrap-only   # bootstrap devices, then exit
#   ./scripts/run.sh --no-keep-awake    # skip keep-awake (Linux only)
#   ./scripts/run.sh -- --relay-only    # explicit relay-only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

KEEP_AWAKE=true
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-keep-awake)
      KEEP_AWAKE=false
      shift
      ;;
    --)
      shift
      ARGS+=("$@")
      break
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#ARGS[@]} -eq 0 ]]; then
  ARGS=(--relay-only)
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "error: missing uv — run ./scripts/install.sh first" >&2
  exit 1
fi

if [[ "$(uname -s)" == "Linux" && "$KEEP_AWAKE" == true ]]; then
  echo "== keep host awake (Linux) =="
  "$SCRIPT_DIR/keep-awake.sh" start
fi

echo "== agent-boot: uv run main.py ${ARGS[*]} =="
exec uv run main.py "${ARGS[@]}"
