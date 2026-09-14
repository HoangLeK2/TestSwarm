# Deploy: media local, farm + go2rtc trên cloud

Topology: `agent-boot` và `media-adapter` chạy ở máy khách sau NAT; `device_farm`
và `go2rtc` chạy trên cloud. Chỉ chiều local → cloud xuyên được NAT, nên adapter
**push** RTSP lên go2rtc thay vì để go2rtc kéo về.

```
LOCAL (sau NAT)                          CLOUD
agent-boot ──────── gRPC :443 ─────────► farm
media-adapter ───── RTSP push :8554 ───► go2rtc ◄── farm khai báo stream
                                                    qua go2rtc:1984 (nội bộ)
browser ─────────── HTTPS :443 ────────► farm ──► signaling ──► go2rtc
browser ◄────────── WebRTC :8555 ──────────────── go2rtc
```

Port public trên cloud: **443, 8554, 8555**. `1984` không ra khỏi compose network.

## Vì sao farm phải khai báo stream trước

go2rtc **từ chối ANNOUNCE cho tên stream nó chưa biết** — publish bị bỏ, stream
không xuất hiện, log không nói gì. Nên phải có ai đó khai báo tên trước.

Việc đó thuộc về farm chứ không phải adapter: adapter nằm ở máy khách, để nó
đăng ký thì phải phơi API go2rtc ra internet. Farm gọi qua network nội bộ nên
`1984` ở yên bên trong. Xem `_go2rtc_ensure_stream` trong
`device_farm/api/routes/media_webrtc.py`.

go2rtc không có API "tạo stream rỗng" — mọi source nó nhận đều là source nó sẽ
dial. Nên placeholder trỏ vào `rtsp://127.0.0.1:9/placeholder` để dial fail tức
thì. **go2rtc trả 400 cho lệnh PUT này, và đó là bình thường** — stream vẫn được
tạo, đó là phần ta cần.

Hệ quả kèm theo: giữa lúc khai báo stream và lúc adapter attach publisher,
stream chỉ có mỗi placeholder, và `/api/webrtc` trả **500**. Farm map 500 thành
**425 + Retry-After** để người xem thử lại, không phải 502 lỗi cứng.

## Bước triển khai

### 1. Cloud — `deploy.env`

Đã điền sẵn, kiểm tra lại:

```bash
RTSP_PASS=...                          # đã sinh sẵn, đổi nếu muốn
GO2RTC_WEBRTC_CANDIDATES='"stun:8555"' # STUN tự dò địa chỉ public
MEDIA_ADAPTER_CONTROL_PLANE=grpc
MEDIA_WEBRTC_SIGNALING_PLANE=backend
DEVICE_FARM_GO2RTC_URL=http://go2rtc:1984
```

Không đặt `MEDIA_ADAPTER_HTTP_URL` ở đây. Fallback đó giả định adapter cùng máy;
để nó sẽ biến lỗi control-plane thành timeout vào một địa chỉ không bao giờ trả lời.

Nếu không muốn phụ thuộc STUN, ghim địa chỉ tường minh và giữ stun làm dự phòng:

```bash
GO2RTC_WEBRTC_CANDIDATES='"203.0.113.10:8555","stun:8555"'
```

Dùng địa chỉ **origin**, không dùng hostname đi qua proxy Cloudflare — tên đã
proxy sẽ resolve về Cloudflare, và Cloudflare không forward 8555.

### 2. Cloud — firewall

Mở `8554/tcp`, `8555/tcp`, `8555/udp`. Nếu muốn siết thêm, giới hạn `8554` theo
IP nguồn của các máy khách; `8555` phải mở cho mọi người xem.

### 3. Cloud — chạy

Có hai đường, tuỳ go2rtc do ai quản lý. Singapore đang ở **đường A**.

#### Đường A — giữ container `go2rtc` standalone (host networking)

Không cần `docker rm`. Chỉ đổi config rồi restart.

```bash
# 1. Xem container đang mount config ở đâu
docker inspect go2rtc --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} RW={{.RW}}{{"\n"}}{{end}}'

# 2. Chép template đã điền mật khẩu đè lên file đó
#    (infra/go2rtc/go2rtc.standalone.yaml, thay PASTE_RTSP_PASS_HERE)

# 3. Khoá file — nếu không, go2rtc sẽ tự ghi đè và làm hỏng nó như hiện tại
chmod 444 <đường-dẫn-config>

# 4. Nạp lại config, container giữ nguyên
docker restart go2rtc

# 5. CHẶN 1984 Ở FIREWALL — đây là thứ duy nhất bịt được API,
#    vì host networking bỏ qua mọi danh sách port của compose
sudo ufw deny 1984

# 6. Dựng farm. go2rtc nằm sau profile nên `up` sẽ KHÔNG đụng vào container cũ
docker compose -f docker-compose.deploy.yml --env-file deploy.env build farm
docker compose -f docker-compose.deploy.yml --env-file deploy.env up -d
```

`deploy.env` phải đặt `DEVICE_FARM_GO2RTC_URL=http://host.docker.internal:1984`.
Tên service `go2rtc` không phân giải được từ farm, vì container host-network
không nằm trong network của compose.

#### Đường B — để compose quản lý go2rtc (bridge)

```bash
docker rm -f go2rtc    # container standalone sẽ đụng cổng 8554/8555
docker compose -f docker-compose.deploy.yml --env-file deploy.env build farm
docker compose -f docker-compose.deploy.yml --env-file deploy.env --profile go2rtc up -d
```

Đặt `DEVICE_FARM_GO2RTC_URL=http://go2rtc:1984`. Đường này `1984` không được
publish nên không cần luật firewall, và file config mount `:ro` nên không bị
ghi đè. Đổi lại là phải tạo lại container.

### 3b. Kiểm tra bắt buộc sau khi chạy

Hai phép thử này quyết định đúng/sai, chạy **từ máy ngoài**:

```bash
# a) API go2rtc KHÔNG được ra internet
curl -m 5 http://194.127.193.184:1984/api/streams     # phải timeout / refused

# b) RTSP phải đòi mật khẩu — DESCRIBE không creds phải trả 401, KHÔNG phải 404
python3 - <<'PY'
import socket
s=socket.create_connection(("194.127.193.184",8554),timeout=8)
s.sendall(b"DESCRIBE rtsp://194.127.193.184:8554/probe RTSP/1.0\r\nCSeq: 1\r\n\r\n")
print(s.recv(512).decode(errors="replace"))
PY
```

Còn trả `200` ở (a) hoặc `404` ở (b) nghĩa là config chưa vào.

Image `farm` **phải build lại** (thay đổi nằm trong `device_farm/`).

Image `agent-boot` **cũng phải build lại và phát hành lại cho từng máy khách**.
Không chỉ là đổi env: đường publish có một lỗi crash phải sửa trong Go
(`writeRemote` đưa cho gortsplib media của RTSP server local thay vì media đã
ANNOUNCE, gây nil pointer dereference và giết cả tiến trình adapter ngay gói đầu
tiên). Máy khách chạy image cũ sẽ crash-loop chứ không phải chỉ thiếu hình.

### 4. Máy khách — `.env`

```bash
MEDIA_ADAPTER_GO2RTC_RTSP_PUBLISH_TEMPLATE=rtsp://farm:<RTSP_PASS>@device-farm.tommadethis.app:8554/{stream_raw}
MEDIA_ADAPTER_GO2RTC_REGISTER_ENABLED=0
MEDIA_ADAPTER_REMOTE_RTSP_QUEUE=256
MEDIA_ADAPTER_CONTROL_GRPC_SERVER=grpc-device-farm.tommadethis.app:443
MEDIA_ADAPTER_CONTROL_GRPC_TLS=true
```

`REGISTER_ENABLED` phải là `0`. Để `1` thì adapter sẽ PUT một src **pull** trỏ về
`:8556` của chính máy khách — địa chỉ cloud không với tới được — và tranh chấp
với publisher trên cùng tên stream.

### 4b. WHIP thay cho RTSP push (tuỳ chọn, khắc phục đứng hình)

RTSP **không có back-channel**: receiver mất gói cũng không có cách nào báo
ngược. Mất một P-frame là hỏng hình cho tới khi có IDR từ nguồn khác — đó là
nguyên nhân gốc của stream đứng phải F5. Publish qua WHIP thì go2rtc negotiate
`nack`, pion retransmit gói mất **mà không đụng tới MediaCodec**.

Transport chọn theo scheme của URL publish, không có cờ thứ hai.

**Trên server** — không được mở thẳng `1984`, đó là API admin (`PUT
/api/streams` ghi config) và ingest WHIP vô tình dùng chung port. Giữ nguyên
`ufw deny 1984`, dựng thêm một hostname reverse proxy 443 → `127.0.0.1:1984`,
chỉ cho `POST /api/webrtc`:

```nginx
server {
    listen 443 ssl;
    server_name whip-device-farm.tommadethis.app;
    # ... ssl_certificate ...

    # Chỉ ingest. Mọi path khác — nhất là /api/streams, /api/config — rơi xuống
    # location / bên dưới và bị chặn.
    location = /api/webrtc {
        limit_except POST { deny all; }
        auth_basic           "whip";
        auth_basic_user_file /etc/nginx/whip.htpasswd;
        proxy_pass http://127.0.0.1:1984/api/webrtc$is_args$args;
        # Signalling là một POST body SDP nhỏ, không phải media.
        proxy_read_timeout 15s;
    }

    location / { return 403; }
}
```

Cloudflare proxy bật được ở hostname này (khác hẳn `rtsp://...:8554`):
signalling chỉ là HTTPS POST, media vẫn đi UDP thẳng tới `8555`.

**Trên máy khách** — đổi đúng một dòng, restart container:

```bash
MEDIA_ADAPTER_GO2RTC_RTSP_PUBLISH_TEMPLATE=https://farm:<WHIP_PASS>@whip-device-farm.tommadethis.app/api/webrtc?dst={stream_raw}
```

Basic auth lấy từ userinfo, Go `net/http` tự gắn header. Backend không đổi.

**Kiểm tra**:

```bash
docker compose logs media-adapter | grep "publishing over WHIP"
curl -s http://127.0.0.1:8878/v1/rtsp/publisher/status | jq '.per_serial'
# rtp_written tăng, write_errors không tăng.
# idr_requests tăng ~20/phút = go2rtc đang bắn PLI trên ticker 2s; khi đó gate
# PLI lại (nack đã sửa mất gói rồi) thay vì để nó reset MediaCodec mỗi 3 giây.

# Proxy phải chặn đúng — dòng này PHẢI trả 403, không phải 200:
curl -u farm:<WHIP_PASS> -X PUT "https://whip-device-farm.tommadethis.app/api/streams?name=x"
```

**Rollback**: trả template về `rtsp://...:8554/{stream_raw}`, restart. Không có
migration, không có state.

**Cái giá**: RTSP publish chỉ cần một kết nối TCP outbound nên sống qua mọi NAT.
WHIP cần UDP tới media port của go2rtc cộng STUN — mạng khách chặn UDP là mất
stream hoàn toàn. Thử một máy trước khi mở cho cả fleet.

### 5. Kiểm tra sau khi lên

```bash
python3 scripts/media_diagnostics.py SERIAL \
  --samples 3 \
  --interval 1 \
  --adapter-url http://127.0.0.1:8878 \
  --go2rtc-url http://127.0.0.1:1984 \
  --docker \
  --env-file deploy.env \
  --fail-on-warning
```

Mong đợi `classification=healthy` khi đang có browser xem, hoặc `no_consumer`
khi chưa có browser. Exit `2` nghĩa là một hop media bị stall; exit `3` nghĩa là
stream đang chạy nhưng runtime config drift so với env file. Xem chi tiết trong
`docs/runbooks/media-stream-diagnostics.md`.

## Cạm bẫy

- **Tên stream phải khớp tuyệt đối** giữa `_go2rtc_stream_name` (Python) và
  `stream.StreamName` (Go, `agent-boot/media-adapter/internal/domain/stream/packet.go`).
  Lệch một ký tự: farm khai báo một tên, adapter đẩy vào tên khác, video im lặng
  không lên. Có test khoá ở `test_go2rtc_stream_name_matches_the_go_adapter_rules`.
- **`i-frame-interval:int=1`** (`internal/adapters/scrcpy/launcher.go`) nghĩa là
  mỗi giây một keyframe. Trước đây chặng RTSP là localhost nên miễn phí; giờ nó
  là đường upload của khách, và keyframe nặng gấp 5–10 lần P-frame. Nếu uplink
  chật, nới lên 2–3s rồi đo lại.
- **Băng thông**: toàn bộ video đi từ đường upload của máy khách. N máy × bitrate.
  Nút thắt sẽ ở đó, không phải ở server.

## Chưa được kiểm chứng

Toàn bộ chuỗi đã chạy end-to-end trên localhost bằng ffmpeg và một probe gortsplib
(xác nhận adapter authenticate được với go2rtc). **Chưa từng chạy với máy Android
thật + media-adapter thật + go2rtc trên cloud thật.** Chạy một máy một phiên qua
đường cloud thật trước khi mở cho khách.
