# agent-boot — Docker Compose (offline bundle)

## Cài nhanh

### macOS / Linux

```bash
tar -xzf agent-boot-docker-0.1.3.tar.gz
cd agent-boot-docker-0.1.3

./scripts/docker-load.sh
cp .env.example .env          # điền RELAY_API_KEY, RELAY_ENROLLMENT_TOKEN, AGENT_BOOT_CONTENT_DATABASE_URL
./scripts/docker-up.sh up -d    # bật ADB host + docker compose up -d
./scripts/docker-up.sh logs -f  # xem log relay
```

### Windows (Docker Desktop, bundle universal)

Phần này áp dụng cho `agent-boot-docker-0.1.3.zip`. Với gói Windows-only
`agent-boot-docker-windows-0.1.3.zip`, làm theo `INSTALL.md` nằm ngay trong ZIP.

**Dùng file `.cmd`** (khuyến nghị — tránh lỗi `.ps1` mở Notepad khi double-click):

```bat
cd agent-boot-docker-0.1.3
scripts\docker-load.cmd
copy .env.example .env
notepad .env                    rem điền 3 giá trị bắt buộc bên dưới
scripts\docker-up.cmd up -d
scripts\docker-up.cmd logs -f
```

Hoặc mở **PowerShell** (không double-click file `.ps1`):

```powershell
Expand-Archive agent-boot-docker-0.1.3.zip -DestinationPath .
cd agent-boot-docker-0.1.3
powershell -ExecutionPolicy Bypass -File .\scripts\docker-load.ps1
copy .env.example .env
notepad .env
powershell -ExecutionPolicy Bypass -File .\scripts\docker-up.ps1 up -d
```

Trong `.env`, bắt buộc điền `RELAY_API_KEY`, `RELAY_ENROLLMENT_TOKEN` và
`AGENT_BOOT_CONTENT_DATABASE_URL`. Script khởi động sẽ từ chối chạy nếu một
trong ba giá trị này còn trống. TLS cert đã có sẵn trong image.

> **Vì sao `.ps1` mở Notepad?** Windows mặc định gắn `.ps1` với trình soạn thảo văn bản. Phải chạy qua `docker-load.cmd` hoặc gọi `powershell -File ...` từ terminal.

Yêu cầu: **Docker Desktop**, **Android Platform-Tools** (`adb` trong PATH), USB debugging trên điện thoại.

Gói chứa **2 image nén** (`-amd64.tar.gz` + `-arm64.tar.gz`, ~165MB tổng). `docker-load.sh` tự chọn theo CPU máy (PC Linux / Mac Intel → amd64, Mac M-series → arm64).

`docker-up.sh` tự:

1. Bật `adb -a nodaemon server` trên **máy host** (nếu port 5037 chưa listen)
2. Chạy `docker compose up -d`

Container mặc định chạy **relay** (`main.py --relay-only`), không chạy `bootstrap.py` trên terminal.

**Cài APK:** farm server gửi lệnh `bootstrap` khi thiết bị online (hoặc bấm *Bootstrap all* trên UI). Image đã bake sẵn `/app/assets/apks/` (STF + u2). Xem log:

```bash
docker compose logs -f agent-boot | grep -iE 'bootstrap|STF|u2 APK'
```

Nếu u2/STF **đã cài trên máy**, log sẽ ghi `already installed` — không reinstall.

## Chỉ dùng docker compose (đã bật ADB host)

```bash
adb -a nodaemon server &        # một lần trên host
docker compose up -d
docker compose logs -f
docker compose down
```

## ADB (bắt buộc global trên host)

USB ở **host**; container kết nối `host.docker.internal:5037`.

**Quan trọng:** ADB server trên máy host phải listen **toàn interface** (`-a`), không phải chỉ `127.0.0.1`. `adb start-server` mặc định chỉ localhost → container Docker **không** thấy thiết bị.

```bash
# Đúng (global — Docker dùng được)
adb kill-server
adb -a -P 5037 nodaemon server &

# Sai (chỉ localhost — container không kết nối được)
adb start-server
```

`./scripts/docker-up.sh` tự bật `adb -a` nếu port 5037 chưa listen, hoặc **restart** nếu phát hiện ADB chỉ bind localhost.

```
Điện thoại ──USB──► adb server (host, 0.0.0.0:5037)
                         ▲
                         │ host.docker.internal:5037
                    agent-boot container (relay)
```

Kiểm tra trên host: `adb devices` → phải có `device`.  
Kiểm tra global: `lsof -nP -iTCP:5037 -sTCP:LISTEN` → phải thấy `*:5037` hoặc `0.0.0.0:5037`, không chỉ `127.0.0.1:5037`.

## Linux: USB trong container (không cần host ADB)

Chỉ khi chạy từ source repo (có `docker-compose.linux-usb.yml`):

```bash
docker compose -f docker-compose.yml -f docker-compose.linux-usb.yml up -d --build
```

## Xử lý sự cố

| Lỗi | Cách xử lý |
|-----|------------|
| `host ADB not reachable` | Trên host: `adb kill-server && adb -a -P 5037 nodaemon server` hoặc `./scripts/docker-up.sh up -d` |
| Host có device, container không thấy | ADB đang localhost-only → restart với `adb -a` (xem mục ADB) |
| `image not found` | `./scripts/docker-load.sh` |
| Container restart loop | `docker compose logs`; kiểm tra `.env` RELAY_* |
| `CERTIFICATE_VERIFY_FAILED` | Rebuild image (`docker build`) — cert chain được fetch lúc build |
| `exec format error` | Chạy lại `./scripts/docker-load.sh` (bundle cũ 1 arch?) — gói mới có cả amd64 + arm64 |
