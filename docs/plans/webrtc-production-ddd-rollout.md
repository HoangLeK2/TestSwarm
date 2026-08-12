# WebRTC Production Rollout With go2rtc

## Target Architecture

```
local phones/ADB -> Go media adapter -> RTSP publish -> cloud go2rtc -> WebRTC/ICE/STUN -> browser
                         ^
                         |
       cloud backend gRPC media-control stream
```

The Python backend must not carry media frames and must not register producer
streams. It owns authentication, authorization, device allocation, session
lease, serial-to-stream-name mapping, and media control-plane commands. The Go
media adapter owns scrcpy startup, video socket ingestion, H264/RTP packetization,
and RTSP publishing. go2rtc owns media ingest, fanout, ICE, and WebRTC
negotiation.

## Bounded Contexts

- Device Control: device state, tap/swipe/input through agent-boot/u2.
- Media Session: short-lived viewer leases and WebRTC signaling proxy.
- Media Source: one go2rtc stream per device, named `device-{serial}` after
  sanitization.
- Media Adapter: reusable Go process that starts scrcpy, reads H264, publishes
  RTSP, and can run independently for streaming.
- Media Transport: RTSP publish from adapter and WHEP/WebRTC to browser.

## Runtime Flow

1. Frontend asks backend `POST /api/media/webrtc/sessions`.
2. Backend resolves the registered local media adapter for the serial and sends
   `start_session` over the adapter's outbound gRPC control stream.
3. Go media adapter starts/reuses scrcpy, requests IDR when needed, and publishes
   H264/RTP directly to `rtsp://<cloud-go2rtc>:8554/device-{serial}`.
4. Backend returns a short-lived session id and maps it to `device-{serial}`.
5. Frontend sends browser SDP offer to
   `POST /api/media/webrtc/sessions/{id}/answer`.
6. Backend sends `answer_session` over the adapter control stream. The adapter
   calls go2rtc signaling API and returns the SDP answer.
7. Browser receives WebRTC directly from go2rtc with ICE/STUN enabled. TURN is
   intentionally skipped for the first production rollout.

## Cloud Backend With Local Adapter

When `device_farm` runs in cloud and phones stay on a local host/rack, the cloud
backend must not call `127.0.0.1`, `host.docker.internal`, or a private LAN IP
for media. Those addresses are local to the cloud container or to one private
network only.

Use this split:

- `agent-boot`: local control/u2 relay, outbound to the cloud gRPC endpoint.
- `media-adapter`: local scrcpy/WebRTC owner, outbound gRPC control to cloud
  backend, outbound RTSP publish to cloud go2rtc.
- `go2rtc`: cloud media gateway; browser receives WebRTC from this node.
- Cloud backend: auth, device state, session lease, signaling metadata; no H264
  frame relay.

STUN-only means WebRTC can work when NAT/firewall allows UDP hole punching or
the cloud go2rtc WebRTC port is reachable. It does not create an HTTP tunnel
from the cloud backend back into the local adapter. TURN stays disabled by
policy.

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
docker compose up -d --build
```

Use `http://127.0.0.1:1984` only for local diagnostics. Browser-facing app code
should continue to call backend `/api/media/webrtc`. For STUN-only go2rtc,
`infra/go2rtc/go2rtc.yaml` fixes WebRTC on port `8555` and advertises
`stun:8555`; expose UDP/TCP `8555` from the media host when viewers are outside
the LAN.
