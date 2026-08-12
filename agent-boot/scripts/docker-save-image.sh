#!/usr/bin/env bash
# Build agent-boot for linux/amd64 + linux/arm64 and export offline image tars.
#
# Usage:
#   ./scripts/docker-save-image.sh
#   ./scripts/docker-save-image.sh 0.1.4
#   ./scripts/docker-save-image.sh 0.1.4 amd64   # single arch only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

ONLY_ARCH="${2:-}"
IMAGE="agent-boot:${VERSION}"
OUT_DIR="$ROOT/dist"
mkdir -p "$OUT_DIR"

ensure_buildx() {
  if ! docker buildx version >/dev/null 2>&1; then
    echo "error: docker buildx is required (Docker Desktop / buildx plugin)" >&2
    exit 1
  fi
  if ! docker buildx inspect agent-boot-multi >/dev/null 2>&1; then
    docker buildx create --name agent-boot-multi --driver docker-container --use >/dev/null
  else
    docker buildx use agent-boot-multi >/dev/null
  fi
  docker buildx inspect --bootstrap >/dev/null
}

build_and_save() {
  local platform="$1"
  local out="$OUT_DIR/agent-boot-image-${VERSION}-${platform}.tar.gz"

  echo "== docker buildx linux/${platform} -> ${out} =="
  docker buildx build \
    --platform "linux/${platform}" \
    -t "${IMAGE}" \
    --provenance=false \
    --sbom=false \
    --load \
    .
  docker save "${IMAGE}" | gzip -9 > "${out}"
  ls -lh "${out}"
}

ensure_buildx

echo "== prepare bootstrap assets (APKs + atx-agent) =="
chmod +x "$ROOT/docker/prepare-assets.sh"
"$ROOT/docker/prepare-assets.sh"

if [[ -n "$ONLY_ARCH" ]]; then
  case "$ONLY_ARCH" in
    amd64|arm64) build_and_save "$ONLY_ARCH" ;;
    *)
      echo "error: unsupported arch '${ONLY_ARCH}' (use amd64 or arm64)" >&2
      exit 1
      ;;
  esac
else
  build_and_save amd64
  build_and_save arm64
fi

echo ""
echo "Docker bundle (both arches + compose + scripts):"
echo "  ./scripts/package-docker-release.sh ${VERSION}"
echo ""
echo "On customer machine:"
echo "  tar -xzf agent-boot-docker-${VERSION}.tar.gz"
echo "  ./scripts/docker-load.sh    # auto-picks amd64 or arm64"
