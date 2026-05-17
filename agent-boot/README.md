# agent-boot

Local agent chạy trên máy có kết nối ADB đến Android devices.  
Kết nối **outbound** đến cloud gRPC server — không cần mở port vào mạng nội bộ.

## Cấu trúc

```
agent-boot/
├── main.py              # Entry point (CLI)
├── bootstrap.py         # One-time device setup
│
├── relay/               # Long-running relay daemon
│   ├── __init__.py      # Re-exports: RelayAgent, start_mdns_discovery, _list_serials
│   ├── agent.py         # RelayAgent — gRPC bidi stream, reconnect, command dispatch
│   ├── adb.py           # ADB helpers (ppadb): shell, connect, restart_u2, probe_caps
│   ├── mdns.py          # mDNS listener — Android 11+ Wireless Debugging auto-discovery
│   ├── device_state.py  # DeviceState FSM + DeviceContext + DeviceRegistry
│   └── device_watcher.py# AdbDeviceWatcher — adb track-devices real-time events
│
├── proto/               # Generated gRPC stubs (DO NOT EDIT manually)
│   ├── __init__.py      # Adds proto/ to sys.path for bare imports in stubs
│   ├── adb_relay_pb2.py
│   └── adb_relay_pb2_grpc.py
│
├── .env                 # RELAY_SERVER, RELAY_API_KEY, RELAY_ENROLLMENT_TOKEN (không commit)
├── .env.example         # Template
└── pyproject.toml
```

## Quick Start

```bash
cp .env.example .env      # điền RELAY_SERVER + RELAY_API_KEY + RELAY_ENROLLMENT_TOKEN
uv run main.py            # bootstrap tất cả devices → start relay
```

## Modes

```bash
uv run main.py                        # bootstrap → relay (default)
uv run main.py --relay-only           # bỏ qua bootstrap, chỉ chạy relay
uv run main.py --bootstrap-only       # setup devices rồi exit
uv run main.py --serial 172.16.0.213:45269   # target device cụ thể
uv run main.py --ws-url ws://host:8081/device-agent  # auto-connect STFService
```

## Environment Variables

| Biến | Default | Mô tả |
|------|---------|--------|
| `RELAY_SERVER` | `localhost:50051` | Địa chỉ gRPC server (`host:port`) |
| `RELAY_API_KEY` | *(bắt buộc)* | Auth key khớp với farm server |
| `RELAY_ENROLLMENT_TOKEN` | *(bắt buộc khi DB bật)* | Token user tạo trong cloud để gán owner cho agent-boot |
| `RELAY_MODE` | `grpc` | Transport: `grpc` hoặc `ws` |
| `DEVICE_FARM_WS` | *(trống)* | URL WebSocket cho STFService auto-connect (e.g. `ws://host:8081/device-agent`) |
| `U2_BATCH_ENABLED` | `true` | Bật u2 batch/flow executor (1 gRPC RTT thay vì 3 HTTP RTT) |
| `AGENT_BOOT_FORCE_U2_INSTALL` | `0` | Set `1` để ép cài lại uiautomator2 APKs; mặc định package đã có thì skip |
| `SCRCPY_VIDEO_CODEC` | `h264` | Codec video gửi đến browser (`h264` only) |
| `SCRCPY_VIDEO_ENCODER` | *(auto)* | Force encoder cụ thể, e.g. `c2.android.avc.encoder` |
| `SCRCPY_FRAME_TIMEOUT_S` | `30` | Giây không có frame trước khi scrcpy restart |
| `AUTO_OPEN_STF_APP` | `0` | Set `1` để tự mở STFService UI sau bootstrap |
| `AGENT_BOOT_EXTRA_ENABLED` | `0` | Bật HTTP ingest `POST /extra-data/xml` cho phone/APK gửi XML trực tiếp về agent |
| `AGENT_BOOT_EXTRA_TOKEN` | *(bắt buộc)* | Shared token; APK gửi qua header `X-Agent-Boot-Extra-Token` |
| `AGENT_BOOT_EXTRA_ALLOW_UNAUTH` | `0` | Chỉ bật cho local debug; cho phép ingest không token |
| `AGENT_BOOT_EXTRA_HOST` | `0.0.0.0` | Host bind của extra-data ingest |
| `AGENT_BOOT_EXTRA_PORT` | `8765` | Port bind của extra-data ingest |
| `AGENT_BOOT_XML_MAX_BYTES` | `8388608` | Giới hạn kích thước XML payload; cần dư cho nhiều snapshot comment trong cùng request |
| `AGENT_BOOT_XML_PARSE_WORKERS` | `1` | Số parse worker chạy song song; vẫn khóa tuần tự theo từng device serial |
| `AGENT_BOOT_CONTENT_DB_ENABLED` | `0` | Bật writer trực tiếp vào `content_items` khi relay chạy |
| `AGENT_BOOT_CONTENT_DATABASE_URL` | *(bắt buộc khi bật writer)* | PostgreSQL URL cho agent DB role insert-only vào `content_items` |
| `AGENT_BOOT_CONTENT_DB_POOL_SIZE` | `1` | Pool size DB writer để tránh agent làm quá tải Postgres |
| `AGENT_BOOT_CONTENT_DB_COMMAND_TIMEOUT` | `10` | Timeout mỗi DB command, giây |
| `AGENT_BOOT_CONTENT_DB_RETRIES` | `3` | Số lần retry insert batch trước khi trả lỗi về APK/device_farm |
| `AGENT_BOOT_CONTENT_DB_RETRY_BASE_DELAY` | `0.2` | Base delay retry insert batch, giây |

## Network Ports

| Port | Hướng | Mục đích |
|------|-------|---------|
| 50051 | agent → server (outbound) | gRPC relay stream |
| 5555 | agent → device | ADB over WiFi |
| 7912 | agent → device | atx-agent (u2 RPC) |
| 8765 | phone/APK → agent (inbound, optional) | Extra-data XML ingest when `AGENT_BOOT_EXTRA_ENABLED=1` |

Mặc định không cần mở inbound port trên máy agent. Khi bật `AGENT_BOOT_EXTRA_ENABLED=1`, phone phải truy cập được `http://<agent-host>:8765/extra-data/xml` trên cùng mạng/VPN.

## Bootstrap steps

| # | Step | Mô tả |
|---|------|--------|
| 1 | adb tcpip | Mở WiFi ADB (chỉ khi kết nối USB) |
| 2 | Wireless Debugging | Enable Android 11+ mDNS (SDK ≥ 30) |
| 3 | uiautomator2 APKs | Install `com.github.uiautomator` + test APK |
| 4 | atx-agent | Push + start atx-agent trên port 7912 |
| 5 | STFService | Install APK |
| 6 | Permissions | Grant WRITE_SECURE_SETTINGS, READ_PHONE_STATE |
| 7 | Auto-connect | Launch STFService + inject `DEVICE_FARM_WS` via ADB intent (không cần scan QR) |

## Relay Architecture

```
┌─────────────────────────────────────────────────────┐
│                  relay/agent.py                      │
│                                                      │
│  RelayAgent ─── gRPC bidi stream ──► Cloud server   │
│       │                                              │
│       ├── AdbDeviceWatcher (adb track-devices)       │  real-time <100ms
│       │     └── DeviceRegistry (state machine)       │
│       │           UNKNOWN → CONNECTING → ONLINE      │
│       │           ONLINE → OFFLINE/RECONNECTING      │
│       │           → DEAD (max retries exceeded)      │
│       │                                              │
│       ├── mDNS Listener (Android 11+ auto-connect)  │
│       └── Periodic heartbeat (30s keepalive)         │
└─────────────────────────────────────────────────────┘
```

**1 gRPC stream / agent** — HTTP/2 multiplexes tất cả devices trong cùng 1 connection.  
Mỗi `AdbCommand` mang `serial` để server route đúng device.

### Device State Machine

```
UNKNOWN ──► CONNECTING ──► ONLINE ◄──► BUSY
                               │
                        crash/unplug
                               │
                    ┌──────────┴──────────┐
               retry_count < 5       retry_count ≥ 5
                    │                     │
               RECONNECTING            DEAD
```

## Regenerate proto stubs

```bash
cd ../device_farm
bash proto/generate.sh
cp proto/generated/adb_relay_pb2*.py ../agent-boot/proto/
```

## Dependencies

```bash
uv add grpcio grpcio-tools zeroconf pure-python-adb
```

| Package | Dùng cho |
|---------|---------|
| `grpcio` | gRPC client stream |
| `zeroconf` | mDNS discovery (Android 11+) |
| `pure-python-adb` | ADB daemon protocol (không cần adb binary) |
| `rich` | Bootstrap UI |
