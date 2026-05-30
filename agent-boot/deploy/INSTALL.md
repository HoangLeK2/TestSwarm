# agent-boot — Docker Compose (offline bundle)

## Cài nhanh

```bash
tar -xzf agent-boot-docker-0.1.0.tar.gz
cd agent-boot-docker-0.1.0

./scripts/docker-load.sh
cp .env.example .env          # sửa RELAY_SERVER, RELAY_API_KEY, RELAY_ENROLLMENT_TOKEN
./scripts/docker-up.sh up -d    # bật ADB host + docker compose up -d
./scripts/docker-up.sh logs -f  # xem log relay
```

`docker-up.sh` tự:

1. Bật `adb -a nodaemon server` trên **máy host** (nếu port 5037 chưa listen)
2. Chạy `docker compose up -d`

Container mặc định chạy **relay**: `uv run main.py --relay-only`.

## Chỉ dùng docker compose (đã bật ADB host)

```bash
adb -a nodaemon server &        # một lần trên host
docker compose up -d
docker compose logs -f
docker compose down
```

## ADB

USB ở **host**; container kết nối `host.docker.internal:5037`.

```
Điện thoại ──USB──► adb server (host)
                         ▲
                         │ host.docker.internal:5037
                    agent-boot container (relay)
```

Kiểm tra trên host: `adb devices` → phải có `device`.

## Linux: USB trong container (không cần host ADB)

Chỉ khi chạy từ source repo (có `docker-compose.linux-usb.yml`):

```bash
docker compose -f docker-compose.yml -f docker-compose.linux-usb.yml up -d --build
```

## Xử lý sự cố

| Lỗi | Cách xử lý |
|-----|------------|
| `host ADB not reachable` | Trên host: `adb -a nodaemon server` hoặc `./scripts/docker-up.sh up -d` |
| `image not found` | `./scripts/docker-load.sh` |
| Container restart loop | `docker compose logs`; kiểm tra `.env` RELAY_* |
| `exec format error` | Sai CPU arch — build lại image trên máy đích |
