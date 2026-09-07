# Media Stream Diagnostics

Use this when a Device Farm stream freezes, starts slowly, or feels laggy.

The probe samples these hops for one serial:

```text
scrcpy/media-adapter -> RTSP push -> go2rtc producer -> WebRTC consumer
```

## Local probe

```bash
python3 scripts/media_diagnostics.py emulator-5554 \
  --samples 3 \
  --interval 1 \
  --adapter-url http://127.0.0.1:8878 \
  --go2rtc-url http://127.0.0.1:1984 \
  --docker \
  --env-file .env
```

If go2rtc API port `1984` is private to Docker, `--docker` falls back to:

```bash
docker exec device-farm-go2rtc-1 wget -qO- http://127.0.0.1:1984/api/streams
```

## Deployment preflight

Run with `--fail-on-warning` before handing a media deploy to users:

```bash
python3 scripts/media_diagnostics.py SERIAL \
  --samples 2 \
  --interval 1 \
  --adapter-url http://127.0.0.1:8878 \
  --go2rtc-url http://127.0.0.1:1984 \
  --docker \
  --env-file deploy.env \
  --fail-on-warning
```

Exit codes:

- `0`: stream counters are healthy, or no browser is attached yet.
- `2`: a media hop is stalled or unreachable.
- `3`: stream counters are healthy but Docker/runtime config drift was detected.

## Classification

- `adapter_unreachable`: media-adapter HTTP is not reachable. Check the local
  adapter process/container before go2rtc.
- `source_stalled`: adapter is reachable, but scrcpy frame/byte counters do not
  move. Check device encoder, secure-screen blackout, ADB, and scrcpy logs.
- `source_frame_gap`: adapter reports a connected stream, but the last frame is
  stale. Request an IDR/keyframe and inspect scrcpy reset logs.
- `go2rtc_unreachable`: go2rtc API is not reachable from the probe. On compose
  deployments this is expected from the host unless `--docker` is used.
- `go2rtc_stream_missing`: farm has not declared the stream name in go2rtc, or
  the backend/adapter stream-name contract diverged.
- `go2rtc_source_missing`: only the placeholder exists; adapter did not publish
  into go2rtc. Check RTSP password, firewall, and `:8554`.
- `publish_stalled`: adapter frame counters move, but go2rtc producer packets do
  not. This points at the RTSP push boundary.
- `go2rtc_consumer_stalled`: producer packets move, but WebRTC consumer packets
  do not. Check ICE candidates, UDP/TCP `:8555`, and browser connection state.
- `degraded_publish_errors`: stream moves but adapter reports publish errors or
  reconnects during the sample window.
- `no_consumer`: source and producer are alive, but no browser is attached.
- `healthy`: source, producer, and consumer counters moved during the sample.

## Config Checks

With `--docker --env-file`, the probe also checks:

- `MEDIA_ADAPTER_GO2RTC_REGISTER_ENABLED=0` for backend-signaled RTSP push.
- go2rtc RTSP username/password match the env file without printing secrets.
- running WebRTC candidates match `GO2RTC_WEBRTC_CANDIDATES`.
- media-adapter exposes the RTSP publish template and realtime queue settings.

Never paste raw RTSP passwords from the report. The probe redacts known secret
fields and strips URL userinfo.
