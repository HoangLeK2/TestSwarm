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

## Docker (macOS — thiết bị USB trên Mac)

USB không vào container được (Docker Desktop chạy VM). Agent trong container gọi **ADB server trên Mac** qua `host.docker.internal:5037`.

### Chạy nhanh (khuyến nghị)

Script tự bật `adb -a` trên host rồi chạy compose:

```bash
./scripts/docker-up.sh --abort-on-container-exit
```

Phải thấy serial + `device` trong log container.

### Chạy relay trong container

```bash
cp .env.example .env   # điền RELAY_SERVER, RELAY_API_KEY, RELAY_ENROLLMENT_TOKEN
./scripts/docker-up.sh run --rm agent-boot bash -lc "uv run main.py --relay-only"
```

### Export image `.tar` (mang sang máy khác, không cần build lại)

```bash
./scripts/docker-save-image.sh
# -> dist/agent-boot-image-0.1.0.tar

docker load -i dist/agent-boot-image-0.1.0.tar
./scripts/docker-up.sh run --rm agent-boot adb devices
```

### Gói ship cho khách (khuyến nghị)

```bash
./scripts/package-docker-release.sh
# -> dist/agent-boot-docker-0.1.0.tar.gz
```

Gói gồm: **image `.tar` + `docker-compose.yml` + `scripts/docker-up.sh` + `.env.example`**.

Khách giải nén → `./scripts/docker-load.sh` → `./scripts/docker-up.sh`.

### Gói source `.tar.gz` vs image `.tar`

| File | Nội dung | Lệnh load |
|------|----------|-----------|
| `dist/agent-boot-docker-0.1.0.tar.gz` | Image + compose + scripts | `tar -xzf` → `docker-load.sh` |
| `dist/agent-boot-0.1.0.tar.gz` | Source + Dockerfile | `tar -xzf` → `docker build` |
| `dist/agent-boot-image-0.1.0.tar` | Chỉ Docker image | `docker load -i` |

ADB server trên Mac host — dùng `./scripts/docker-up.sh` (tự bật `adb -a` khi cần).

## Gói này không gồm

- `.env` (secret)
- `.venv` (tạo lại bằng `uv sync` trên máy khách)
- Mã nguồn Farm server — chỉ agent relay local

## Hỗ trợ

Nếu `adb devices` trống: kiểm tra cáp USB, driver (Windows), và “USB debugging” trên điện thoại.
