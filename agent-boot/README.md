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
```

## Bootstrap steps

| # | Step | Mô tả |
|---|------|--------|
| 1 | adb tcpip | Mở WiFi ADB (chỉ khi kết nối USB) |
| 2 | Wireless Debugging | Enable Android 11+ mDNS (SDK ≥ 30) |
| 3 | uiautomator2 APKs | Install `com.github.uiautomator` + test APK |
| 4 | atx-agent | Push + start atx-agent trên port 7912 |
| 5 | STFService | Install APK |
| 6 | Permissions | Grant WRITE_SECURE_SETTINGS, READ_PHONE_STATE |
| 7 | Open app | Launch STFService → scan QR để connect cloud |

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
