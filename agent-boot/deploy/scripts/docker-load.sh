#!/usr/bin/env bash
# Load the agent-boot image tar matching this machine's CPU (amd64 or arm64).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

host_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *)
      echo "error: unsupported host CPU '$(uname -m)' (need x86_64 or aarch64)" >&2
      exit 1
      ;;
  esac
}

ARCH="$(host_arch)"

shopt -s nullglob
arch_tars=(agent-boot-image-*-"${ARCH}".tar.gz agent-boot-image-*-"${ARCH}".tar)
legacy_tars=(agent-boot-image-*.tar.gz agent-boot-image-*.tar)
shopt -u nullglob

pick_tar() {
  if [[ ${#arch_tars[@]} -eq 1 ]]; then
    echo "${arch_tars[0]}"
    return
  fi
  if [[ ${#arch_tars[@]} -gt 1 ]]; then
    echo "error: multiple image tars for ${ARCH}: ${arch_tars[*]}" >&2
    exit 1
  fi

  # Legacy single-arch bundle (no -amd64/-arm64 suffix).
  local legacy=()
  for t in "${legacy_tars[@]}"; do
    [[ "$t" == *-amd64.tar* || "$t" == *-arm64.tar* ]] && continue
    legacy+=("$t")
  done
  if [[ ${#legacy[@]} -eq 1 ]]; then
    echo "warning: legacy single-arch bundle — may fail with exec format error on wrong CPU" >&2
    echo "${legacy[0]}"
    return
  fi
  if [[ ${#legacy[@]} -gt 1 ]]; then
    echo "error: multiple legacy image tars found: ${legacy[*]}" >&2
    exit 1
  fi

  echo "error: no image tar for ${ARCH} in $ROOT" >&2
  echo "  expected: agent-boot-image-<version>-${ARCH}.tar.gz" >&2
  exit 1
}

load_tar() {
  local tar="$1"
  case "$tar" in
    *.tar.gz|*.tgz)
      echo "== gunzip -c ${tar} | docker load =="
      gunzip -c "$tar" | docker load
      ;;
    *)
      echo "== docker load -i ${tar} =="
      docker load -i "$tar"
      ;;
  esac
}

TAR="$(pick_tar)"
echo "== host arch: ${ARCH} =="
load_tar "$TAR"

echo ""
echo "Next: cp .env.example .env && ./scripts/docker-up.sh up -d"
