#!/usr/bin/env bash
# Keep a Linux farm host awake while agent-boot runs (no suspend on screen off / lid close).
# Prefer: ./scripts/run.sh  (starts keep-awake + relay together)
#
# Usage:
#   ./keep-awake.sh start          # run until stopped (survives SSH disconnect if nohup)
#   ./keep-awake.sh stop
#   ./keep-awake.sh status
#   ./keep-awake.sh install        # persistent config (requires sudo)
#   ./keep-awake.sh uninstall      # revert persistent config (requires sudo)
set -euo pipefail

PIDFILE="${HOME}/.device-farm-keep-awake.pid"
LOGFILE="${HOME}/.device-farm-keep-awake.log"
LOGIND_DROPIN="/etc/systemd/logind.conf.d/device-farm-no-suspend.conf"

is_running() {
  [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

start() {
  if is_running; then
    echo "keep-awake already running (PID $(cat "$PIDFILE"))"
    exit 0
  fi

  if ! command -v systemd-inhibit >/dev/null 2>&1; then
    echo "Missing: systemd-inhibit (install systemd package)" >&2
    exit 1
  fi

  nohup systemd-inhibit \
    --what=idle:sleep:shutdown:handle-lid-switch:handle-power-key \
    --who="device-farm" \
    --why="Keep farm host awake for remote SSH and agent-boot" \
    sleep infinity >>"$LOGFILE" 2>&1 &

  echo $! >"$PIDFILE"
  echo "keep-awake started (PID $(cat "$PIDFILE"))"
  echo "log: $LOGFILE"
}

stop() {
  if ! is_running; then
    rm -f "$PIDFILE"
    echo "keep-awake not running"
    exit 0
  fi

  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "keep-awake stopped"
}

status_cmd() {
  if is_running; then
    echo "keep-awake running (PID $(cat "$PIDFILE"))"
  else
    echo "keep-awake not running"
    exit 1
  fi
}

install_persistent() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run: sudo $0 install" >&2
    exit 1
  fi

  mkdir -p "$(dirname "$LOGIND_DROPIN")"
  cat >"$LOGIND_DROPIN" <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
IdleAction=ignore
IdleActionSec=0
EOF
  echo "Wrote $LOGIND_DROPIN"

  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart systemd-logind
    echo "Restarted systemd-logind"
  fi

  if command -v gsettings >/dev/null 2>&1; then
    local user home
    user="${SUDO_USER:-}"
    if [[ -n "$user" && "$user" != "root" ]]; then
      home="$(getent passwd "$user" | cut -d: -f6)"
      if [[ -n "$home" && -d "$home" ]]; then
        sudo -u "$user" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$user")/bus" \
          gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null || true
        sudo -u "$user" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$user")/bus" \
          gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing' 2>/dev/null || true
        sudo -u "$user" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$user")/bus" \
          gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0 2>/dev/null || true
        sudo -u "$user" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$user")/bus" \
          gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 0 2>/dev/null || true
        echo "Updated GNOME power settings for $user (if desktop session is active)"
      fi
    fi
  fi

  echo "Persistent keep-awake config installed."
  echo "Tip: also run '$0 start' after reboot, or add to your login profile."
}

uninstall_persistent() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run: sudo $0 uninstall" >&2
    exit 1
  fi

  if [[ -f "$LOGIND_DROPIN" ]]; then
    rm -f "$LOGIND_DROPIN"
    echo "Removed $LOGIND_DROPIN"
  else
    echo "No persistent config at $LOGIND_DROPIN"
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart systemd-logind
    echo "Restarted systemd-logind"
  fi

  echo "Persistent keep-awake config removed."
}

usage() {
  cat <<EOF
Usage: $0 {start|stop|status|install|uninstall}

  start      Block suspend/shutdown via systemd-inhibit (background)
  stop       Stop background keep-awake
  status     Show whether keep-awake is running
  install    Persist: ignore lid close + idle suspend (sudo)
  uninstall  Remove persistent config (sudo)
EOF
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status_cmd ;;
  install) install_persistent ;;
  uninstall) uninstall_persistent ;;
  -h|--help|help) usage ;;
  *)
    usage >&2
    exit 1
    ;;
esac
