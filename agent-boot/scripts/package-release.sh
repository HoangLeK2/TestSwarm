#!/usr/bin/env bash
# Package agent-boot source for customer delivery (no secrets, no local venv).
#
# Usage:
#   ./scripts/package-release.sh
#   ./scripts/package-release.sh 0.2.0
#
# Output:
#   dist/agent-boot-<version>.tar.gz
#   dist/agent-boot-<version>.zip   (if `zip` is available)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

NAME="agent-boot-${VERSION}"
OUT_DIR="$ROOT/dist"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "$OUT_DIR"
DEST="$STAGING/$NAME"
mkdir -p "$DEST"

RSYNC=(rsync -a --delete
  --exclude-from="$ROOT/scripts/package-excludes.txt"
  --exclude 'scripts/package-release.sh'
)

if ! command -v rsync >/dev/null 2>&1; then
  echo "error: rsync is required" >&2
  exit 1
fi

"${RSYNC[@]}" "$ROOT/" "$DEST/"

# Customer-facing helpers (always fresh from repo scripts/).
mkdir -p "$DEST/scripts"
cp "$ROOT/scripts/install.sh" "$DEST/scripts/install.sh"
chmod +x "$DEST/scripts/install.sh"
for helper in docker-up.sh docker-save-image.sh; do
  if [[ -f "$ROOT/scripts/$helper" ]]; then
    cp "$ROOT/scripts/$helper" "$DEST/scripts/$helper"
    chmod +x "$DEST/scripts/$helper"
  fi
done
if [[ -f "$ROOT/scripts/install.ps1" ]]; then
  cp "$ROOT/scripts/install.ps1" "$DEST/scripts/install.ps1"
fi
cp "$ROOT/INSTALL.md" "$DEST/INSTALL.md"

# Sanity: never ship secrets.
if [[ -f "$DEST/.env" ]]; then
  echo "error: .env must not be in customer package" >&2
  exit 1
fi

TAR="$OUT_DIR/${NAME}.tar.gz"
tar -czf "$TAR" -C "$STAGING" "$NAME"

echo "Created: $TAR"
ls -lh "$TAR"

if command -v zip >/dev/null 2>&1; then
  ZIP="$OUT_DIR/${NAME}.zip"
  (cd "$STAGING" && zip -rq "$ZIP" "$NAME")
  echo "Created: $ZIP"
  ls -lh "$ZIP"
fi

echo ""
echo "Ship: $TAR (and/or .zip). Customer copies .env.example -> .env and fills secrets locally."
