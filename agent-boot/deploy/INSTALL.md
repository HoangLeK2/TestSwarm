# agent-boot — Docker bundle (image + compose)

Gói này gồm:

- `agent-boot-image-<version>.tar` — Docker image (`docker load`)
- `docker-compose.yml` — cấu hình chạy chuẩn
- `scripts/docker-load.sh` — load image
- `scripts/docker-up.sh` — bật ADB trên Mac host + `docker compose`

**Không chứa** `.env` (secret). Copy từ `.env.example` trên máy khách.

## Yêu cầu (macOS)

- Docker Desktop
- `adb` trên Mac: `brew install android-platform-tools`
- Điện thoại USB debugging

## Cài đặt

```bash
tar -xzf agent-boot-docker-0.1.0.tar.gz
cd agent-boot-docker-0.1.0

./scripts/docker-load.sh
cp .env.example .env
# Sửa RELAY_SERVER, RELAY_API_KEY, RELAY_ENROLLMENT_TOKEN trong .env
```

## Test ADB (container → host ADB → điện thoại)

```bash
./scripts/docker-up.sh --abort-on-container-exit
```

Phải thấy serial + `device`.

## Chạy relay agent

```bash
./scripts/docker-up.sh run --rm agent-boot \
  bash -lc "uv run main.py --relay-only"
```

## Lưu ý

- USB ở **Mac host**; container chỉ là ADB client qua `host.docker.internal:5037`.
- `docker-up.sh` tự bật `adb -a` trên host nếu port 5037 chưa listen.
- Image build trên Mac Apple Silicon thường là `linux/arm64` — máy đích cần tương thích.
