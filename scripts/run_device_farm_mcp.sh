#!/usr/bin/env sh
# Chạy MCP stdio server của device_farm (Cursor/IDE hoặc client khác).
# Cấu hình lấy từ device_farm/.env (xem .env.example). Backend phải đang chạy.
# Từ repo root: ./scripts/run_device_farm_mcp.sh
# Từ device_farm: python -m mcp.server

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/device_farm"
if [ -d ".venv" ]; then
  . .venv/bin/activate
fi
exec python -m mcp.server
