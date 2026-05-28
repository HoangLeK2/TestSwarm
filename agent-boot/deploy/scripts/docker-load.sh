#!/usr/bin/env bash
# Load agent-boot-image-*.tar from bundle root (same directory as docker-compose.yml).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

shopt -s nullglob
tars=(agent-boot-image-*.tar)
shopt -u nullglob

if [[ ${#tars[@]} -eq 0 ]]; then
  echo "error: no agent-boot-image-*.tar in $ROOT" >&2
  exit 1
fi

if [[ ${#tars[@]} -gt 1 ]]; then
  echo "error: multiple image tars found: ${tars[*]}" >&2
  exit 1
fi

TAR="${tars[0]}"
echo "== docker load -i ${TAR} =="
docker load -i "$TAR"

echo ""
echo "Next: ./scripts/docker-up.sh --abort-on-container-exit"
