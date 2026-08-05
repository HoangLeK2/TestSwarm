# Media Adapter

The media adapter owns local scrcpy video capture and publishes H264 to RTSP for go2rtc/WebRTC.

## Stream Capacity Benchmark

Run the synthetic stream benchmark from this directory:

```sh
GOCACHE=/Users/hoangle/farm/device-farm/.tmp/go-build-cache \
go run ./cmd/stream-bench \
  --streams 200 \
  --duration 60s \
  --fps 15 \
  --readers-per-stream 1 \
  --rtsp-address 127.0.0.1:18559 \
  --max-drop-ratio 0.01 \
  --min-reader-packet-ratio 0.95
```

Useful ramp:

```sh
go run ./cmd/stream-bench --streams 50 --duration 30s --fps 15 --readers-per-stream 1 --rtsp-address 127.0.0.1:18551
go run ./cmd/stream-bench --streams 100 --duration 30s --fps 15 --readers-per-stream 1 --rtsp-address 127.0.0.1:18552
go run ./cmd/stream-bench --streams 200 --duration 60s --fps 15 --readers-per-stream 1 --rtsp-address 127.0.0.1:18553
go run ./cmd/stream-bench --streams 400 --duration 60s --fps 15 --readers-per-stream 1 --rtsp-address 127.0.0.1:18554
```

Read these fields first:

- `drop_ratio`: publisher-side packet loss from queue drops, stale drops, or write errors.
- `reader_packet_ratio`: RTP packets received by attached benchmark RTSP readers.
- `publisher.queue_drops`: adapter cannot drain per-stream queues fast enough.
- `publisher.stale_drops`: adapter is preserving realtime behavior by dropping old non-key packets.
- `publisher.write_errors`: RTSP write path or client path is failing.
- `memory` and `goroutines`: local resource trend as stream count grows.

For production acceptance, use `--duration 300s` or longer on the same host class as the phone rack and keep `drop_ratio <= 0.01`, `reader_packet_ratio >= 0.95`, and `reader_failures = 0`.

Local short-run baseline after the no-copy/RW-lock hot-path optimization:

- `800` streams, `15fps`, `1` RTSP reader per stream, `5s`: `drop_ratio=0`, `reader_packet_ratio=1`, heap alloc about `39.5 MB`.
- `1200` streams, `15fps`, `1` RTSP reader per stream, `5s`: `drop_ratio=0`, `reader_packet_ratio=1`, heap alloc about `64.5 MB`.
