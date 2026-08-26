# agent-boot — Docker (Windows)

Gói **Windows only** (linux/amd64). Chạy trên PC Windows với **Docker Desktop**.

## Yêu cầu

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) — bật và đợi engine sẵn sàng
2. [Android Platform-Tools](https://developer.android.com/tools/releases/platform-tools) — thêm `adb` vào PATH
3. Điện thoại: bật **USB debugging**, cắm USB (hoặc Wi‑Fi ADB đã ghép)

## Cài nhanh

Giải nén `agent-boot-docker-windows-0.2.8.zip`, mở **CMD** hoặc **PowerShell** trong thư mục đó:

```bat
scripts\docker-load.cmd
copy .env.example .env
notepad .env
scripts\docker-up.cmd up -d
scripts\docker-up.cmd logs -f
docker compose logs -f media-adapter
```

Trong `.env`, bắt buộc điền ba giá trị đang để trống:

- `RELAY_API_KEY`
- `RELAY_ENROLLMENT_TOKEN`
- `AGENT_BOOT_CONTENT_DATABASE_URL`

`AGENT_BOOT_CONTENT_DB_ENABLED=1` đã được bật để content writer hoạt động.
Database URL phải là PostgreSQL credential giới hạn quyền, cấp riêng cho khách
hàng; không dùng tài khoản owner/superuser. Các env vận hành còn lại đã có đầy
đủ giá trị mặc định trong `.env.example`. Script khởi động sẽ từ chối chạy nếu
ba giá trị bắt buộc chưa được điền.

WebRTC video cần go2rtc chạy ở host hoặc media node mà container truy cập được.
Mặc định media adapter publish H264 tại
`rtsp://host.docker.internal:8556/device-{serial}` và tự gọi go2rtc API
`http://host.docker.internal:1984`. Nếu go2rtc không chạy trên cùng máy Windows,
sửa `MEDIA_ADAPTER_GO2RTC_RTSP_SOURCE_TEMPLATE` và `MEDIA_ADAPTER_GO2RTC_URL`
trong `.env`.

Chính sách media hiện tại là **ICE/STUN only**, không dùng TURN. Nếu backend
`device_farm` chạy trên cloud, cloud backend không gọi trực tiếp được adapter
trên máy Windows qua `127.0.0.1`, `host.docker.internal` hoặc IP LAN. Browser
cần tới được WebRTC endpoint của go2rtc qua LAN, port-forward UDP/TCP `8555`,
hoặc VPN/edge network. RTSP `8556` và go2rtc API `1984` chỉ dùng nội bộ giữa
adapter và go2rtc, không publish công khai.

(TLS cert đã có trong image.)

> **Không double-click file `.ps1`** — Windows mở Notepad. Dùng `.cmd` hoặc:
>
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\scripts\docker-load.ps1
> powershell -ExecutionPolicy Bypass -File .\scripts\docker-up.ps1 up -d
> ```

## ADB trên máy host (bắt buộc)

USB nằm ở host; container gọi ADB qua `host.docker.internal:5037`.

ADB server phải listen **global** (`-a`), không chỉ `127.0.0.1`:

```bat
adb kill-server
adb -a -P 5037 nodaemon server
```

`scripts\docker-up.cmd` tự bật `adb -a` nếu cần. Kiểm tra trên host:

```bat
adb devices
```

Phải thấy thiết bị ở trạng thái `device`.

```
Điện thoại ──USB──► adb server (host, 0.0.0.0:5037)
                         ▲
                         │ host.docker.internal:5037
                    agent-boot container (relay)
```

## Lệnh thường dùng

```bat
scripts\docker-up.cmd up -d
scripts\docker-up.cmd logs -f
scripts\docker-up.cmd ps
scripts\docker-up.cmd down
```

Relay ID tự sinh được lưu trong Docker volume `agent-boot-state`, nên vẫn giữ
nguyên sau `down`/`up`. Chỉ `docker compose down -v` mới xóa identity này.
Compose dùng **1 image / 2 container**:

- `agent-boot`: relay control/u2/gRPC.
- `media-adapter`: scrcpy/WebRTC media hot path, đọc scrcpy video socket và publish sang go2rtc.

Backend không còn nhận video qua gRPC. Xem log riêng:

```bat
docker compose logs -f agent-boot
docker compose logs -f media-adapter
docker compose restart media-adapter
```

Luôn dùng `scripts\docker-up.cmd` để `up`/`restart`, vì wrapper kiểm tra secret
và ADB trước khi khởi động. Có thể dùng Docker Compose trực tiếp cho các lệnh
quan sát hoặc dừng:

```bat
docker compose logs -f
docker compose ps
docker compose down
```

## Bootstrap APK

Container chạy **relay** (`--relay-only`). Khi mới cắm phone, agent-boot chỉ
report serial lên backend; không tự push STF/u2/atx cho phone chưa đăng ký.
Farm gửi lệnh bootstrap sau khi user đăng ký phone, hoặc khi user bấm
*Bootstrap all* trên UI. Image có sẵn `/app/assets/apks/` (STF + u2).

```bat
docker compose logs -f agent-boot
```

## Xử lý sự cố

| Lỗi | Cách xử lý |
|-----|------------|
| `host ADB not reachable` | `adb kill-server` rồi `adb -a -P 5037 nodaemon server` hoặc chạy lại `scripts\docker-up.cmd up -d` |
| Host có máy, container không thấy | ADB đang localhost-only → restart với `adb -a` |
| `image not found` | `scripts\docker-load.cmd` |
| Container restart loop | `docker compose logs`; kiểm tra `.env` (`RELAY_*`) |
| Content writer báo lỗi kết nối | Kiểm tra `AGENT_BOOT_CONTENT_DATABASE_URL`, firewall/VPN và quyền insert của PostgreSQL role |
| `exec format error` | Gói này chỉ cho PC Windows x86_64 (amd64). Máy ARM Windows cần gói khác |
| Docker daemon not running | Mở Docker Desktop, đợi sẵn sàng, rồi thử lại |
