#!/usr/bin/env bash
# macOS Docker Desktop: start host ADB (all interfaces), then docker compose (pre-loaded image).
#
# Usage:
#   ./scripts/docker-up.sh
#   ./scripts/docker-up.sh --abort-on-container-exit
#   ./scripts/docker-up.sh run --rm agent-boot bash -lc "uv run main.py --relay-only"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

AGENT_BOOT_VERSION="${AGENT_BOOT_VERSION:-0.1.0}"
IMAGE="agent-boot:${AGENT_BOOT_VERSION}"
ADB_PORT="${ADB_PORT:-5037}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: missing command: $1" >&2
    exit 1
  fi
}

need_cmd adb
need_cmd docker

if ! docker compose version >/dev/null 2>&1; then
  echo "error: docker compose (v2) is required" >&2
  exit 1
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "error: image ${IMAGE} not found. Run: ./scripts/docker-load.sh" >&2
  exit 1
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$ADB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "== ADB server already listening on port ${ADB_PORT} =="
else
  echo "== Starting host ADB server (0.0.0.0:${ADB_PORT}) =="
  adb kill-server 2>/dev/null || true
  nohup adb -a -P "$ADB_PORT" nodaemon server >/tmp/agent-boot-adb-server.log 2>&1 &
  sleep 1
  if ! lsof -nP -iTCP:"$ADB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "error: ADB server did not start; see /tmp/agent-boot-adb-server.log" >&2
    exit 1
  fi
fi

echo "== Host devices =="
adb -P "$ADB_PORT" devices || true

compose_subcommands=(up run build down ps logs exec pull stop restart config)

if [[ $# -eq 0 ]]; then
  set -- up --abort-on-container-exit
else
  is_subcommand=false
  for sub in "${compose_subcommands[@]}"; do
    if [[ "$1" == "$sub" ]]; then
      is_subcommand=true
      break
    fi
  done
  if [[ "$is_subcommand" == false ]]; then
    set -- up "$@"
  fi
fi

echo "== docker compose $* =="
exec docker compose "$@"
