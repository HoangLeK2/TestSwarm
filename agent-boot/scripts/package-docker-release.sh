#!/usr/bin/env bash
# Ship universal Docker bundle: amd64 + arm64 images + compose + scripts.
#
# Usage:
#   ./scripts/package-docker-release.sh
#   ./scripts/package-docker-release.sh 0.1.2
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
for ps1 in docker-up.ps1 docker-load.ps1; do
  if [[ -f "$ROOT/deploy/scripts/$ps1" ]]; then
    cp "$ROOT/deploy/scripts/$ps1" "$DEST/scripts/$ps1"
  fi
done
for cmd in docker-up.cmd docker-load.cmd; do
  if [[ -f "$ROOT/deploy/scripts/$cmd" ]]; then
    cp "$ROOT/deploy/scripts/$cmd" "$DEST/scripts/$cmd"
  fi
done
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

if command -v zip >/dev/null 2>&1; then
  ZIP="$OUT_DIR/${NAME}.zip"
  (cd "$STAGING" && zip -rq "$ZIP" "$NAME")
  echo "Created: $ZIP"
  ls -lh "$ZIP"
fi

echo ""
echo "Universal bundle (amd64 + arm64). Ship one file:"
echo "  $(basename "$BUNDLE_TAR")  (macOS/Linux)"
echo "  $(basename "$ZIP")  (Windows — if zip was built)"
echo ""
echo "Customer (macOS/Linux):"
echo "  1) tar -xzf $(basename "$BUNDLE_TAR") && cd $NAME"
echo "  2) ./scripts/docker-load.sh     # auto-picks CPU arch"
echo "  3) cp .env.example .env && edit RELAY_API_KEY + RELAY_ENROLLMENT_TOKEN"
echo "  4) ./scripts/docker-up.sh up -d"
echo ""
echo "Customer (Windows — CMD hoặc double-click):"
echo "  1) Giải nén agent-boot-docker-${VERSION}.zip"
echo "  2) cd agent-boot-docker-${VERSION}"
echo "  3) scripts\\docker-load.cmd"
echo "  4) copy .env.example .env  # edit RELAY_API_KEY + RELAY_ENROLLMENT_TOKEN"
echo "  5) scripts\\docker-up.cmd up -d"
echo ""
echo "Customer (Windows PowerShell — mở terminal PowerShell, không double-click .ps1):"
echo "  powershell -ExecutionPolicy Bypass -File .\\scripts\\docker-load.ps1"
