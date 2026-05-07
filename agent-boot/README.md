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
├── .env                 # RELAY_SERVER, RELAY_API_KEY (không commit)
├── .env.example         # Template
└── pyproject.toml
```

## Quick Start

```bash
cp .env.example .env      # điền RELAY_SERVER + RELAY_API_KEY
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
| `RELAY_MODE` | `grpc` | Transport: `grpc` hoặc `ws` |
| `DEVICE_FARM_WS` | *(trống)* | URL WebSocket cho STFService auto-connect (e.g. `ws://host:8081/device-agent`) |
| `U2_BATCH_ENABLED` | `true` | Bật u2 batch/flow executor (1 gRPC RTT thay vì 3 HTTP RTT) |
| `SCRCPY_VIDEO_CODEC` | `h264` | Codec video gửi đến browser (`h264` only) |
| `SCRCPY_VIDEO_ENCODER` | *(auto)* | Force encoder cụ thể, e.g. `c2.android.avc.encoder` |
| `SCRCPY_FRAME_TIMEOUT_S` | `30` | Giây không có frame trước khi scrcpy restart |
| `AUTO_OPEN_STF_APP` | `0` | Set `1` để tự mở STFService UI sau bootstrap |

## Network Ports

| Port | Hướng | Mục đích |
|------|-------|---------|
| 50051 | agent → server (outbound) | gRPC relay stream |
| 5555 | agent → device | ADB over WiFi |
| 7912 | agent → device | atx-agent (u2 RPC) |

Không cần mở inbound port trên máy agent.

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
