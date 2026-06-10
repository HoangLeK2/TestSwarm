# agent-boot — Cài đặt (khách hàng)

Gói này **không chứa** API key hay token. Mỗi máy tự tạo file `.env` từ `.env.example`.

## Yêu cầu

| Thành phần | macOS | Linux | Windows |
|------------|-------|-------|---------|
| Python | 3.13 | 3.13 | 3.13 |
| [uv](https://github.com/astral-sh/uv) | Cài qua script bên dưới | Cùng | `install.ps1` |
| **adb** | `brew install android-platform-tools` | `apt install adb` | Android Platform-Tools + PATH |
| Điện thoại | USB debugging hoặc Wireless debugging | Cùng | Cùng |

## Cài nhanh

### macOS / Linux

```bash
cd agent-boot
./scripts/install.sh
```

### Windows (PowerShell)

```powershell
cd agent-boot
.\scripts\install.ps1
```

## Cấu hình

```bash
cp .env.example .env
```

Chỉnh tối thiểu:

- `RELAY_SERVER` — địa chỉ Farm (ví dụ `your-farm.example.com:50051`)
- `RELAY_API_KEY` — do nhà cung cấp Farm cấp
- `RELAY_ENROLLMENT_TOKEN` — tạo trên trang Relay Agents của Farm

**Không** gửi file `.env` qua email/chat.

## Chạy

```bash
adb devices          # phải thấy serial + "device"
uv run main.py --relay-only
```

Bootstrap lần đầu (cài STF/u2 trên máy):

```bash
uv run main.py
```

## Docker Compose

USB trên **host** (macOS Docker Desktop); container chạy relay, gọi ADB qua `host.docker.internal:5037`.

### Chạy relay (khuyến nghị)

```bash
cp .env.example .env   # điền RELAY_SERVER, RELAY_API_KEY, RELAY_ENROLLMENT_TOKEN
./scripts/docker-up.sh up -d    # adb host + docker compose up -d
./scripts/docker-up.sh logs -f
```

Hoặc thủ công:

```bash
adb -a nodaemon server &
docker compose up -d --build
docker compose logs -f
```

### Linux: USB trong container

```bash
docker compose -f docker-compose.yml -f docker-compose.linux-usb.yml up -d --build
```

### Export image `.tar` (mang sang máy khác)

```bash
./scripts/docker-save-image.sh
# -> dist/agent-boot-image-0.1.0.tar

docker load -i dist/agent-boot-image-0.1.0.tar
./scripts/docker-up.sh up -d
```

### Gói ship cho khách (khuyến nghị)

```bash
./scripts/package-docker-release.sh
# -> dist/agent-boot-docker-0.1.0.tar.gz
```

Gói gồm: **image amd64 + arm64** + `docker-compose.yml` + scripts + `.env.example` (một file zip chạy mọi CPU).

Khách giải nén → `./scripts/docker-load.sh` (tự chọn arch) → `./scripts/docker-up.sh`.

### Gói source `.tar.gz` vs image `.tar`

| File | Nội dung | Lệnh load |
|------|----------|-----------|
| `dist/agent-boot-docker-0.1.0.tar.gz` | Image + compose + scripts | `tar -xzf` → `docker-load.sh` |
| `dist/agent-boot-0.1.0.tar.gz` | Source + Dockerfile | `tar -xzf` → `docker build` |
| `dist/agent-boot-image-0.1.0-amd64.tar` | Image PC/Linux | `docker load -i` |
| `dist/agent-boot-image-0.1.0-arm64.tar` | Image Mac M-series | `docker load -i` |

ADB server trên Mac host — dùng `./scripts/docker-up.sh` (tự bật `adb -a` khi cần).

## Gói này không gồm

- `.env` (secret)
- `.venv` (tạo lại bằng `uv sync` trên máy khách)
- Mã nguồn Farm server — chỉ agent relay local

## Hỗ trợ

Nếu `adb devices` trống: kiểm tra cáp USB, driver (Windows), và “USB debugging” trên điện thoại.
