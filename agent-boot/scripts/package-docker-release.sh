#!/usr/bin/env bash
# Ship universal Docker bundle: amd64 + arm64 images + compose + scripts.
#
# Usage:
#   ./scripts/package-docker-release.sh
#   ./scripts/package-docker-release.sh 0.1.0
#
# Output:
#   dist/agent-boot-docker-<version>.tar.gz
#   dist/agent-boot-image-<version>-amd64.tar.gz
#   dist/agent-boot-image-<version>-arm64.tar.gz

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

NAME="agent-boot-docker-${VERSION}"
OUT_DIR="$ROOT/dist"
IMAGE_AMD64="$OUT_DIR/agent-boot-image-${VERSION}-amd64.tar.gz"
IMAGE_ARM64="$OUT_DIR/agent-boot-image-${VERSION}-arm64.tar.gz"
BUNDLE_TAR="$OUT_DIR/${NAME}.tar.gz"

mkdir -p "$OUT_DIR"

if [[ ! -f "$IMAGE_AMD64" ]] || [[ ! -f "$IMAGE_ARM64" ]]; then
  echo "== Building multi-arch image tars (missing amd64 and/or arm64) =="
  "$ROOT/scripts/docker-save-image.sh" "$VERSION"
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
cp "$IMAGE_AMD64" "$DEST/agent-boot-image-${VERSION}-amd64.tar.gz"
cp "$IMAGE_ARM64" "$DEST/agent-boot-image-${VERSION}-arm64.tar.gz"

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
ls -lh "$BUNDLE_TAR" "$BUNDLE_TAR_PLAIN" "$IMAGE_AMD64" "$IMAGE_ARM64"
echo ""
echo "Universal bundle (amd64 + arm64). Ship one file:"
echo "  $(basename "$BUNDLE_TAR")"
echo ""
echo "Customer:"
echo "  1) tar -xzf $(basename "$BUNDLE_TAR") && cd $NAME"
echo "  2) ./scripts/docker-load.sh     # auto-picks CPU arch"
echo "  3) cp .env.example .env && edit RELAY_API_KEY + RELAY_ENROLLMENT_TOKEN"
echo "  4) ./scripts/docker-up.sh up -d"
