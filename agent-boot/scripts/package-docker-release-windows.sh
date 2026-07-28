#!/usr/bin/env bash
# Ship Windows-only Docker bundle: amd64 image + Windows scripts + zip.
#
# Usage:
#   ./scripts/package-docker-release-windows.sh
#   ./scripts/package-docker-release-windows.sh 0.1.0
#   REUSE_IMAGE=1 ./scripts/package-docker-release-windows.sh   # explicitly reuse existing amd64 tar
#
# Output:
#   dist/agent-boot-docker-windows-<version>.zip
#   dist/agent-boot-image-<version>-amd64.tar.gz   (reused / built)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

NAME="agent-boot-docker-windows-${VERSION}"
OUT_DIR="$ROOT/dist"
IMAGE_AMD64="$OUT_DIR/agent-boot-image-${VERSION}-amd64.tar.gz"
ZIP="$OUT_DIR/${NAME}.zip"

mkdir -p "$OUT_DIR"

if [[ ! -f "$IMAGE_AMD64" ]] || [[ "${REUSE_IMAGE:-0}" != "1" ]]; then
  echo "== Building linux/amd64 image tar =="
  "$ROOT/scripts/docker-save-image.sh" "$VERSION" amd64
else
  echo "== Reusing existing linux/amd64 image tar (REUSE_IMAGE=1) =="
fi

if [[ ! -f "$IMAGE_AMD64" ]]; then
  echo "error: missing $IMAGE_AMD64" >&2
  exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

DEST="$STAGING/$NAME"
mkdir -p "$DEST/scripts"

cp "$ROOT/deploy/docker-compose.yml" "$DEST/docker-compose.yml"
if [[ -f "$ROOT/deploy/INSTALL.windows.md" ]]; then
  cp "$ROOT/deploy/INSTALL.windows.md" "$DEST/INSTALL.md"
else
  cp "$ROOT/deploy/INSTALL.md" "$DEST/INSTALL.md"
fi

CUSTOMER_ENV="$ROOT/deploy/.env.customer.example"
if [[ ! -f "$CUSTOMER_ENV" ]]; then
  echo "error: missing customer-safe env template: $CUSTOMER_ENV" >&2
  exit 1
fi
cp "$CUSTOMER_ENV" "$DEST/.env.example"

# Customer bundles must contain each secret key exactly once in the canonical
# empty form. Count optional dotenv "export" assignments too, so a second
# effective value cannot bypass validation.
SECRET_CUSTOMER_ENV_KEYS=(
  RELAY_API_KEY
  RELAY_ENROLLMENT_TOKEN
  AGENT_BOOT_CONTENT_DATABASE_URL
)
for key in "${SECRET_CUSTOMER_ENV_KEYS[@]}"; do
  assignment_count="$(
    grep -Ec \
      "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" \
      "$DEST/.env.example" \
      || true
  )"
  if [[ "$assignment_count" -ne 1 ]] || ! grep -Eq \
    "^[[:space:]]*${key}[[:space:]]*=[[:space:]]*$" \
    "$DEST/.env.example"; then
    echo "error: customer env template must contain one empty ${key} assignment" >&2
    exit 1
  fi
done
CONTENT_DB_ENABLED_LINES="$(
  grep -Ec '^[[:space:]]*AGENT_BOOT_CONTENT_DB_ENABLED[[:space:]]*=' "$DEST/.env.example" \
    || true
)"
if [[ "$CONTENT_DB_ENABLED_LINES" -ne 1 ]] || ! grep -Eq \
  '^[[:space:]]*AGENT_BOOT_CONTENT_DB_ENABLED[[:space:]]*=[[:space:]]*1([[:space:]]*(#.*)?)?$' \
  "$DEST/.env.example"; then
  echo "error: customer env template must enable direct database writes" >&2
  exit 1
fi
REQUIRED_CUSTOMER_ENV_KEYS=(
  RELAY_API_KEY
  RELAY_ENROLLMENT_TOKEN
  AGENT_BOOT_CONTENT_DATABASE_URL
  RELAY_MODE
  RELAY_SERVER
  RELAY_GRPC_TLS
  ADB_HOST
  ADB_PORT
  ADB_WAIT_SECONDS
  AGENT_BOOT_STARTUP_MODE
  AGENT_BOOT_AUTO_BOOTSTRAP
  AGENT_BOOT_CONTENT_DB_ENABLED
  AGENT_BOOT_CONTENT_DB_POOL_SIZE
  AGENT_BOOT_CONTENT_DB_COMMAND_TIMEOUT
  AGENT_BOOT_CONTENT_DB_RETRIES
  AGENT_BOOT_CAPTURE_SCREENSHOT
  RELAY_ADB_POOL_SIZE
  RELAY_U2_POOL_SIZE
  SCRCPY_DEFAULT_MAX_FPS
  SCRCPY_DEFAULT_MAX_WIDTH
  SCRCPY_DEFAULT_BITRATE
)
for key in "${REQUIRED_CUSTOMER_ENV_KEYS[@]}"; do
  assignment_count="$(
    grep -Ec "^[[:space:]]*${key}[[:space:]]*=" "$DEST/.env.example" || true
  )"
  if [[ "$assignment_count" -ne 1 ]]; then
    echo "error: customer env template must contain exactly one ${key} assignment" >&2
    exit 1
  fi
done

for ps1 in docker-up.ps1 docker-load.ps1; do
  cp "$ROOT/deploy/scripts/$ps1" "$DEST/scripts/$ps1"
done
for cmd in docker-up.cmd docker-load.cmd; do
  cp "$ROOT/deploy/scripts/$cmd" "$DEST/scripts/$cmd"
done

cp "$IMAGE_AMD64" "$DEST/agent-boot-image-${VERSION}-amd64.tar.gz"

sed -i '' "s|image: agent-boot:.*|image: agent-boot:${VERSION}|" "$DEST/docker-compose.yml" 2>/dev/null \
  || sed -i "s|image: agent-boot:.*|image: agent-boot:${VERSION}|" "$DEST/docker-compose.yml"

if [[ -f "$DEST/.env" ]]; then
  echo "error: .env must not be in docker bundle" >&2
  exit 1
fi

# Exclude macOS/Linux shell helpers from Windows zip (keep .cmd + .ps1 only).
rm -f "$DEST/scripts/"*.sh 2>/dev/null || true

if ! command -v zip >/dev/null 2>&1; then
  echo "error: zip is required to build the Windows bundle" >&2
  exit 1
fi

rm -f "$ZIP"
(cd "$STAGING" && zip -rq "$ZIP" "$NAME")

echo "Created: $ZIP"
ls -lh "$ZIP" "$IMAGE_AMD64"
echo ""
echo "Windows bundle (amd64 only). Ship:"
echo "  $(basename "$ZIP")"
echo ""
echo "Customer:"
echo "  1) Giải nén $(basename "$ZIP")"
echo "  2) cd $NAME"
echo "  3) scripts\\docker-load.cmd"
echo "  4) copy .env.example .env"
echo "     edit RELAY_API_KEY + RELAY_ENROLLMENT_TOKEN + AGENT_BOOT_CONTENT_DATABASE_URL"
echo "  5) scripts\\docker-up.cmd up -d"
