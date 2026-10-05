#!/usr/bin/env bash
# Expose Device Farm server (port 8081) via ngrok.
# Sau khi chạy: copy URL https://xxx.ngrok-free.app vào app agent và .env frontend.

set -e
PORT="${1:-8081}"

if ! command -v ngrok >/dev/null 2>&1; then
  echo "Cần cài ngrok: https://ngrok.com/download"
  exit 1
fi

echo "=============================================="
echo "  Device Farm — Ngrok tunnel port $PORT"
echo "  (Điện thoại khác WiFi/4G vẫn kết nối được)"
echo "=============================================="
echo ""
echo "1. Server đang chạy: cd backend && uv run main.py"
echo "2. Chạy script này: ./scripts/ngrok.sh"
echo "3. Copy URL https://... vào:"
echo "   - App STFService (điện thoại): Server URL = wss://<URL>"
echo "   - Frontend .env.local (nếu dùng): NEXT_PUBLIC_* trỏ tới https/wss://<URL>"
echo "4. Điện thoại bất kỳ mạng nào → mở app → kết nối qua ngrok URL."
echo ""
echo "Đang mở tunnel..."
exec ngrok http "$PORT"
