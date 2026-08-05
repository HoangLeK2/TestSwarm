#!/usr/bin/env bash
# Host runs ADB (USB/Wi‑Fi devices); container is ADB client via host.docker.internal:5037.
# Works on macOS (Docker Desktop) and Linux (Docker Engine + compose plugin).
#
# Usage:
#   ./scripts/docker-up.sh
#   ./scripts/docker-up.sh --abort-on-container-exit
#   ./scripts/docker-up.sh run --rm agent-boot bash -lc "uv run main.py --relay-only"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

AGENT_BOOT_VERSION="${AGENT_BOOT_VERSION:-0.1.4}"
IMAGE="agent-boot:${AGENT_BOOT_VERSION}"
ADB_PORT="${ADB_PORT:-5037}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: missing command: $1" >&2
    exit 1
  fi
}

adb_port_listening() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN
    return
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$port" >/dev/null 2>&1
    return
  fi
  # Last resort: try connecting via adb itself.
  adb -P "$port" get-state >/dev/null 2>&1
}

# Docker reaches the host via host.docker.internal — ADB must listen on all interfaces (-a),
# not only 127.0.0.1 (default `adb start-server`).
adb_server_is_global() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null \
      | grep -qE "(^|\s)\*:${port}\s|0\.0\.0\.0:${port}\s|\[::\]:${port}\s"
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null \
      | grep -qE "0\.0\.0\.0:${port}|\[::\]:${port}"
    return
  fi
  return 0
}

start_global_adb_server() {
  echo "== Starting host ADB server (global 0.0.0.0:${ADB_PORT}, flag -a) =="
  adb kill-server 2>/dev/null || true
  nohup adb -a -P "$ADB_PORT" nodaemon server >/tmp/agent-boot-adb-server.log 2>&1 &
  sleep 1
  if ! adb_port_listening "$ADB_PORT"; then
    echo "error: ADB server did not start; see /tmp/agent-boot-adb-server.log" >&2
    exit 1
  fi
  if ! adb_server_is_global "$ADB_PORT"; then
    echo "error: ADB is up but not listening globally — Docker cannot use host ADB" >&2
    echo "  required: adb kill-server && adb -a -P ${ADB_PORT} nodaemon server" >&2
    exit 1
  fi
}

need_cmd adb
need_cmd docker

if ! docker info >/dev/null 2>&1; then
  echo "error: Docker daemon is not running." >&2
  echo "  macOS: open -a Docker   (wait until whale icon is steady)" >&2
  echo "  then: docker info" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "error: docker compose (v2) is required" >&2
  exit 1
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "error: image ${IMAGE} not found. Run: ./scripts/docker-load.sh" >&2
  exit 1
fi

if adb_port_listening "$ADB_PORT"; then
  if adb_server_is_global "$ADB_PORT"; then
    echo "== ADB server already listening globally on port ${ADB_PORT} =="
  else
    echo "warning: ADB on :${ADB_PORT} is localhost-only — restarting with -a (global)" >&2
    start_global_adb_server
  fi
else
  start_global_adb_server
fi

echo "== Host devices =="
adb -P "$ADB_PORT" devices || true

compose_subcommands=(up run build down ps logs exec pull stop restart config)

if [[ $# -eq 0 ]]; then
  set -- up -d
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
