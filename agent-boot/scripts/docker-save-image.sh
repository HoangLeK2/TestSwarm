#!/usr/bin/env bash
# Build agent-boot image and export docker save tarball for offline install.
#
# Usage:
#   ./scripts/docker-save-image.sh
#   ./scripts/docker-save-image.sh 0.1.0
#   ./scripts/docker-save-image.sh 0.1.0 dist/agent-boot-image-0.1.0.tar
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

IMAGE="agent-boot:${VERSION}"
OUT="${2:-$ROOT/dist/agent-boot-image-${VERSION}.tar}"

mkdir -p "$(dirname "$OUT")"

echo "== docker build ${IMAGE} =="
docker build -t "$IMAGE" .

echo "== docker save -> ${OUT} =="
docker save -o "$OUT" "$IMAGE"
ls -lh "$OUT"

echo ""
echo "Docker bundle (image + compose + scripts):"
echo "  ./scripts/package-docker-release.sh ${VERSION}"
echo ""
echo "On another machine (image only):"
echo "  docker load -i $(basename "$OUT")"
echo "  docker run --rm -e ADB_SERVER_SOCKET=tcp:host.docker.internal:5037 ${IMAGE} adb devices"
