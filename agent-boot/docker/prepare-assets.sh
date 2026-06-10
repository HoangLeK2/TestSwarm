#!/usr/bin/env bash
# Stage device bootstrap assets into agent-boot/assets/ before docker build.
# Sources (first match wins):
#   1. device_farm/bundle/  (monorepo dev build)
#   2. agent-boot/STFService.apk + existing assets/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ASSETS="$ROOT/assets"
BUNDLE="$ROOT/../device_farm/bundle"

mkdir -p "$ASSETS/apks" "$ASSETS/atx-agent"

copy_if_newer() {
  local src="$1" dest="$2"
  [[ -f "$src" ]] || return 0
  if [[ ! -f "$dest" ]] || [[ "$src" -nt "$dest" ]]; then
    cp "$src" "$dest"
  fi
}

if [[ -d "$BUNDLE/apks" ]]; then
  for apk in STFService.apk app-uiautomator.apk app-uiautomator-test.apk; do
    copy_if_newer "$BUNDLE/apks/$apk" "$ASSETS/apks/$apk"
  done
fi

if [[ -d "$BUNDLE/atx-agent" ]]; then
  for bin in atx-agent-arm64 atx-agent-arm atx-agent-amd64 atx-agent-386; do
    copy_if_newer "$BUNDLE/atx-agent/$bin" "$ASSETS/atx-agent/$bin"
  done
fi

# Legacy single-file layout (bootstrap.py)
copy_if_newer "$ROOT/STFService.apk" "$ASSETS/apks/STFService.apk"

missing=()
for f in STFService.apk app-uiautomator.apk app-uiautomator-test.apk; do
  [[ -f "$ASSETS/apks/$f" ]] || missing+=("$f")
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "warning: missing APK(s) in $ASSETS/apks/: ${missing[*]}" >&2
  echo "  run: python ../device_farm/download_bundle.py" >&2
  echo "  or place APKs under agent-boot/assets/apks/" >&2
else
  du -sh "$ASSETS"
  ls -lh "$ASSETS/apks/"
fi
