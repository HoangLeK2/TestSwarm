#!/usr/bin/env bash
# Ship Docker image tar + compose bundle (no source code).
#
# Usage:
#   ./scripts/package-docker-release.sh
#   ./scripts/package-docker-release.sh 0.1.0
#
# Output:
#   dist/agent-boot-docker-<version>.tar.gz
#   dist/agent-boot-image-<version>.tar   (also copied inside bundle)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

NAME="agent-boot-docker-${VERSION}"
OUT_DIR="$ROOT/dist"
IMAGE_TAR="$OUT_DIR/agent-boot-image-${VERSION}.tar"
BUNDLE_TAR="$OUT_DIR/${NAME}.tar.gz"

mkdir -p "$OUT_DIR"

if [[ ! -f "$IMAGE_TAR" ]]; then
  echo "== Building image tar (missing $IMAGE_TAR) =="
  "$ROOT/scripts/docker-save-image.sh" "$VERSION" "$IMAGE_TAR"
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

DEST="$STAGING/$NAME"
mkdir -p "$DEST/scripts"

cp "$ROOT/deploy/docker-compose.yml" "$DEST/docker-compose.yml"
cp "$ROOT/deploy/INSTALL.md" "$DEST/INSTALL.md"
cp "$ROOT/.env.example" "$DEST/.env.example"
cp "$ROOT/deploy/scripts/docker-up.sh" "$DEST/scripts/docker-up.sh"
cp "$ROOT/deploy/scripts/docker-load.sh" "$DEST/scripts/docker-load.sh"
chmod +x "$DEST/scripts/docker-up.sh" "$DEST/scripts/docker-load.sh"
cp "$IMAGE_TAR" "$DEST/agent-boot-image-${VERSION}.tar"

# Pin image tag in compose (must match docker-save-image.sh).
sed -i '' "s|image: agent-boot:.*|image: agent-boot:${VERSION}|" "$DEST/docker-compose.yml" 2>/dev/null \
  || sed -i "s|image: agent-boot:.*|image: agent-boot:${VERSION}|" "$DEST/docker-compose.yml"

if [[ -f "$DEST/.env" ]]; then
  echo "error: .env must not be in docker bundle" >&2
  exit 1
fi

BUNDLE_TAR_PLAIN="$OUT_DIR/${NAME}.tar"
tar -czf "$BUNDLE_TAR" -C "$STAGING" "$NAME"
tar -cf "$BUNDLE_TAR_PLAIN" -C "$STAGING" "$NAME"

echo "Created: $BUNDLE_TAR"
echo "Created: $BUNDLE_TAR_PLAIN  (uncompressed, for scp/rsync)"
ls -lh "$BUNDLE_TAR" "$BUNDLE_TAR_PLAIN"
echo ""
echo "Ship to customer:"
echo "  1) tar -xzf $(basename "$BUNDLE_TAR") && cd $NAME"
echo "  2) ./scripts/docker-load.sh"
echo "  3) cp .env.example .env && edit secrets"
echo "  4) ./scripts/docker-up.sh up -d"
echo ""
echo "Image tar (standalone): $IMAGE_TAR"
