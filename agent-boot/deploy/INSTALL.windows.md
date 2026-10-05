# agent-boot — Docker (Windows)

Gói **Windows only** (linux/amd64). Chạy trên PC Windows với **Docker Desktop**.

## Yêu cầu

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) — bật và đợi engine sẵn sàng
2. [Android Platform-Tools](https://developer.android.com/tools/releases/platform-tools) — thêm `adb` vào PATH
3. Điện thoại: bật **USB debugging**, cắm USB (hoặc Wi‑Fi ADB đã ghép)

## Cài nhanh

Giải nén `agent-boot-docker-windows-0.3.2.zip`, mở **CMD** hoặc **PowerShell** trong thư mục đó:

```bat
scripts\docker-load.cmd
copy .env.example .env
notepad .env
scripts\docker-up.cmd up -d
scripts\docker-up.cmd logs -f
docker compose logs -f media-adapter
```

Trong `.env`, bắt buộc điền hai giá trị credential đang để trống:

- `RELAY_API_KEY`
- `RELAY_ENROLLMENT_TOKEN`

Content extract được gửi về farm trong chính reply relay hiện hữu, nên máy khách
hàng không cần — và không nhận — PostgreSQL credential nào. Các env vận hành còn
lại đã có đầy đủ giá trị mặc định trong `.env.example`. Script khởi động sẽ từ
chối chạy nếu hai giá trị bắt buộc chưa được điền.

WebRTC video dùng WHIP outbound từ media-adapter trên máy Windows lên go2rtc của
farm. `.env.example` đã đặt
`MEDIA_ADAPTER_GO2RTC_RTSP_PUBLISH_TEMPLATE=https://webrtc-device-farm.tommadethis.app/api/webrtc?dst={stream_raw}`.
Giữ `MEDIA_ADAPTER_GO2RTC_REGISTER_ENABLED=0`. Nếu mạng khách hàng chặn UDP,
operator có thể đổi lại URL RTSP được cấp riêng rồi recreate `media-adapter`.

Media-adapter cũng mở control gRPC outbound tới farm qua
`MEDIA_ADAPTER_CONTROL_GRPC_SERVER`; mặc định giá trị này đã có trong
`.env.example`. Không cần mở port inbound trên máy Windows và không cần
PostgreSQL credential.

Chính sách media hiện tại là **ICE/STUN only**, không dùng TURN. Nếu backend
`device_farm` chạy trên cloud, cloud backend không gọi trực tiếp được adapter
trên máy Windows qua `127.0.0.1`, `host.docker.internal` hoặc IP LAN. Browser
cần tới được WebRTC endpoint của go2rtc qua LAN, port-forward UDP/TCP `8555`,
hoặc VPN/edge network. RTSP `8554` chỉ dùng cho đường publish outbound từ
adapter lên farm, không cần mở inbound trên máy Windows.

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

Relay ID do server cấp khi đăng ký lần đầu và lưu ở thư mục `./state` cạnh
`docker-compose.yml`, nên giữ nguyên qua `down`, `down -v` và nâng cấp image.
Mất luôn thư mục đó cũng không sinh máy mới: server nhận lại đúng hàng cũ theo
activation code. Tên máy đặt trong admin console, agent không bao giờ ghi đè.
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
| Content uplink báo lỗi | Kiểm tra kết nối relay và log farm `content_uplink_*` |
| `exec format error` | Gói này chỉ cho PC Windows x86_64 (amd64). Máy ARM Windows cần gói khác |
| Docker daemon not running | Mở Docker Desktop, đợi sẵn sàng, rồi thử lại |
