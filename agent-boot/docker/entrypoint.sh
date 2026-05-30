#!/usr/bin/env bash
# Wait for ADB (host server or local USB), then exec the container command (relay by default).
set -euo pipefail

adb_server_ready() {
  local out
  out="$(adb "$@" devices 2>&1)" || return 1
  [[ "$out" != *"cannot connect"* && "$out" != *"Connection refused"* && "$out" != *"failed to connect"* ]]
}

wait_seconds="${ADB_WAIT_SECONDS:-120}"
elapsed=0
use_host=false
ADB_HOST="${ADB_HOST:-host.docker.internal}"
ADB_PORT="${ADB_PORT:-5037}"

if [[ -z "${ADB_SERVER_SOCKET:-}" ]]; then
  echo "== ADB mode: local (USB in container) =="
  while (( elapsed < wait_seconds )); do
    if adb_server_ready; then
      break
    fi
    if (( elapsed == 0 )); then
      echo "entrypoint: waiting for local ADB server / USB ..."
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  if (( elapsed >= wait_seconds )); then
    echo "error: local ADB not ready after ${wait_seconds}s" >&2
    exit 1
  fi
  echo "== ADB devices (local) =="
  adb devices || true
else
  use_host=true
  if [[ "$ADB_SERVER_SOCKET" =~ ^tcp:([^:]+):([0-9]+)$ ]]; then
    ADB_HOST="${BASH_REMATCH[1]}"
    ADB_PORT="${BASH_REMATCH[2]}"
  fi
  export ADB_SERVER_SOCKET="tcp:${ADB_HOST}:${ADB_PORT}"
  echo "== ADB mode: host server ${ADB_HOST}:${ADB_PORT} =="
  while (( elapsed < wait_seconds )); do
    if adb_server_ready -H "$ADB_HOST" -P "$ADB_PORT"; then
      break
    fi
    if (( elapsed == 0 )); then
      echo "entrypoint: waiting for host ADB at ${ADB_HOST}:${ADB_PORT} ..."
      echo "  On host: adb -a -P ${ADB_PORT} nodaemon server"
      echo "  Or: ./scripts/docker-up.sh up -d"
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  if (( elapsed >= wait_seconds )); then
    echo "error: host ADB not reachable at ${ADB_HOST}:${ADB_PORT} after ${wait_seconds}s" >&2
    exit 1
  fi
  echo "== ADB devices (host ${ADB_HOST}:${ADB_PORT}) =="
  adb -H "$ADB_HOST" -P "$ADB_PORT" devices || true
fi
unset use_host

if [[ $# -eq 0 ]]; then
  set -- uv run main.py --relay-only
fi

exec "$@"
