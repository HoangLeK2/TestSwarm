#!/usr/bin/env sh
# Chạy MCP stdio server của backend (Cursor/IDE hoặc client khác).
# Cấu hình lấy từ backend/.env (xem .env.example). Backend phải đang chạy.
# Từ repo root: ./scripts/run_device_farm_mcp.sh
# Từ backend: python -m mcp.server

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
if [ -d ".venv" ]; then
  . .venv/bin/activate
fi
exec python -m mcp.server
