#!/usr/bin/env bash
# Fetch atx-agent binaries into app/src/main/assets/atx-agent/<abi>/
# Run from STFService.apk directory.

set -e
VERSION="${ATX_AGENT_VERSION:-0.10.0}"
BASE="https://github.com/openatx/atx-agent/releases/download/${VERSION}"
ASSETS="app/src/main/assets/atx-agent"

mkdir -p "$ASSETS/arm64-v8a" "$ASSETS/armeabi-v7a"

fetch() {
  local name=$1
  local abi_dir=$2
  local url="${BASE}/${name}"
  echo "Fetching $url ..."
  tmp=$(mktemp -d)
  curl -sL "$url" | tar -xzf - -C "$tmp"
  if [ -f "$tmp/atx-agent" ]; then
    cp "$tmp/atx-agent" "$ASSETS/$abi_dir/atx-agent"
  elif [ -f "$tmp"/*/atx-agent ]; then
    cp "$tmp"/*/atx-agent "$ASSETS/$abi_dir/atx-agent"
  fi
  rm -rf "$tmp"
  test -f "$ASSETS/$abi_dir/atx-agent" && echo "  -> $ASSETS/$abi_dir/atx-agent" || echo "  -> failed"
}

fetch "atx-agent_${VERSION}_linux_arm64.tar.gz" "arm64-v8a"
fetch "atx-agent_${VERSION}_linux_armv7.tar.gz" "armeabi-v7a"

echo "Done. Rebuild the APK."
