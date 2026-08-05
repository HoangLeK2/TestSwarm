# WebRTC Production Rollout With go2rtc

## Target Architecture

```
scrcpy H264 Annex-B -> Go media adapter -> ffmpeg RTSP publish -> go2rtc -> WebRTC/WHEP -> browser
                                               ^
                                               |
                                      agent-boot scrcpy lifecycle
```

The Python backend must not carry media frames and must not register producer
streams. It owns authentication, authorization, device allocation, session
lease, serial-to-stream-name mapping, and WebRTC signaling proxy. The Go media
adapter owns scrcpy video socket ingestion and RTSP publishing. go2rtc owns
media ingest, fanout, ICE, RTP packetization, and WebRTC negotiation.

## Bounded Contexts

- Device Control: device state, scrcpy attach/detach, tap/swipe/input.
- Media Session: short-lived viewer leases and WebRTC signaling proxy.
- Media Source: one go2rtc stream per device, named `device-{serial}` after
  sanitization.
- Media Adapter: reusable Go process that reads scrcpy H264 and publishes RTSP.
- Media Transport: RTSP publish from adapter and WHEP/WebRTC to browser.

## Runtime Flow

1. Frontend asks backend `POST /api/media/webrtc/sessions`.
2. Backend returns a short-lived session id and maps it to `device-{serial}`.
3. Agent-boot starts/reuses the scrcpy source for the device.
4. Go media adapter connects the scrcpy video/control-video sockets, requests
   IDR when needed, and publishes H264 to `rtsp://<go2rtc>:8554/device-{serial}`.
5. Frontend sends browser SDP offer to
   `POST /api/media/webrtc/sessions/{id}/answer`.
6. Backend checks stream readiness and proxies the offer to
   `go2rtc /api/webrtc?src=device-{serial}`.
7. Browser receives WebRTC directly from go2rtc with ICE/STUN enabled. TURN is
   intentionally skipped for the first production rollout.

## Scale Rules

- Grid previews must not open WebRTC sessions for every phone.
- Use WebRTC for focused/control surfaces only.
- Keep dashboard preview as snapshot or very low FPS H264.
- Shard go2rtc per relay/site; do not centralize all devices onto one media node.
- Keep media path on the relay/media node: do not pipe frames through Python
  backend or frontend API routes.
- Measure session churn, active consumers, RTSP producers, CPU, UDP drops, and
  startup-to-first-frame before raising FPS/bitrate.

## Local Run

```bash
docker compose up -d --build
cd agent-boot
MEDIA_ADAPTER_ENABLED=1 \
MEDIA_ADAPTER_DIRECT_SCRCPY_ENABLED=1 \
GO2RTC_RTSP_URL_TEMPLATE=rtsp://127.0.0.1:8554/{stream_raw} \
RELAY_MODE=grpc \
RELAY_SERVER=127.0.0.1:50051 \
RELAY_GRPC_TLS=false \
RELAY_GRPC_ROOT_CERT_FILE= \
uv run main.py
```

Use `http://127.0.0.1:1984` only for local diagnostics. Browser-facing app code
should continue to call backend `/api/media/webrtc`.
