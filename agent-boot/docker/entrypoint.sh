#!/usr/bin/env bash
# Configure ADB, then start relay immediately unless legacy startup explicitly
# requests the old ADB-before-process behavior.
set -euo pipefail

adb_server_ready() {
  local out
  out="$(adb "$@" devices 2>&1)" || return 1
  [[ "$out" != *"cannot connect"* && "$out" != *"Connection refused"* && "$out" != *"failed to connect"* ]]
}

wait_seconds="${ADB_WAIT_SECONDS:-120}"
elapsed=0
ADB_HOST="${ADB_HOST:-host.docker.internal}"
ADB_PORT="${ADB_PORT:-5037}"
startup_mode="${AGENT_BOOT_STARTUP_MODE:-relay-first}"
require_adb="${AGENT_BOOT_REQUIRE_ADB_AT_START:-0}"

if [[ -z "${ADB_SERVER_SOCKET:-}" ]]; then
  echo "== ADB mode: local (USB in container) =="
else
  if [[ "$ADB_SERVER_SOCKET" =~ ^tcp:([^:]+):([0-9]+)$ ]]; then
    ADB_HOST="${BASH_REMATCH[1]}"
    ADB_PORT="${BASH_REMATCH[2]}"
  fi
  export ADB_SERVER_SOCKET="tcp:${ADB_HOST}:${ADB_PORT}"
  # adbutils/uiautomator2 (extra_data) reads these; adb CLI uses ADB_SERVER_SOCKET.
  export ANDROID_ADB_SERVER_HOST="${ADB_HOST}"
  export ANDROID_ADB_SERVER_PORT="${ADB_PORT}"
  echo "== ADB mode: host server ${ADB_HOST}:${ADB_PORT} =="
fi

if [[ "$startup_mode" == "legacy" || "$require_adb" =~ ^(1|true|yes|on)$ ]]; then
  if [[ -z "${ADB_SERVER_SOCKET:-}" ]]; then
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
    while (( elapsed < wait_seconds )); do
      if adb_server_ready -H "$ADB_HOST" -P "$ADB_PORT"; then
        break
      fi
      if (( elapsed == 0 )); then
        echo "entrypoint: waiting for host ADB at ${ADB_HOST}:${ADB_PORT} ..."
        echo "  On host (required global -a, not default localhost-only):"
        echo "    adb kill-server && adb -a -P ${ADB_PORT} nodaemon server"
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
else
  echo "entrypoint: relay-first; ADB readiness will be reconciled in background"
fi

if [[ $# -eq 0 ]]; then
  set -- /app/.venv/bin/python main.py
fi

exec "$@"
