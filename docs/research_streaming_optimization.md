# Research Report: Device Farm Streaming Optimization on Docker

**Date:** 2026-04-11  
**Scope:** Reduce streaming lag on Docker + fix u2 WebSocket disconnects

---

## Executive Summary

Two separate problems: (1) **H264 streaming lag in Docker** caused by network overhead, buffer bloat, and suboptimal scrcpy settings; (2) **u2 WebSocket disconnects** caused by Docker/reverse-proxy idle timeouts killing long-lived connections. Both are solvable with config changes + minor code tweaks — no architecture rewrite needed.

---

## Problem 1: Streaming Lag on Docker

### Root Causes (ordered by impact)

#### 1.1 Docker Network Overhead (Bridge NAT)
Docker's default `bridge` network adds NAT + iptables overhead per packet. For high-throughput H264 streams, this adds 5-15ms latency per hop.

**Fix:**
```yaml
# docker-compose.yml
services:
  farm:
    network_mode: "host"  # bypass bridge NAT entirely
```
If `host` mode isn't possible (port conflicts), use `macvlan`:
```yaml
networks:
  farm_net:
    driver: macvlan
    driver_opts:
      parent: eth0
```

#### 1.2 Scrcpy Bitrate Too High for Relay
Current: `scrcpy_bitrate: 8000000` (8Mbps local), `scrcpy_relay_bitrate: 900000` (900kbps relay).

8Mbps is excessive for Docker→browser path. Large I-frames cause burst congestion, leading to frame queuing.

**Fix:**
```yaml
# config.yaml - tune down for Docker deployment
scrcpy_bitrate: 2000000        # 2Mbps (local ADB in Docker)
scrcpy_relay_bitrate: 800000   # 800kbps (relay, keep)
scrcpy_max_fps: 15             # 15fps is smooth enough for control
scrcpy_max_width: 480          # smaller = less data
```

**Why:** At 540px width + 8Mbps, each IDR keyframe can be 200-400KB. Over Docker bridge, this creates 20-40ms burst delay. At 2Mbps + 480px, IDR drops to ~50KB.

#### 1.3 WebSocket Frame Backpressure
Current congestion detection in `ws.py:439`: `lag_ms > 100.0 OR version_gap > 3`

100ms lag threshold is too generous. By the time lag hits 100ms, frames are already queuing.

**Fix (ws.py):**
```python
# Tighter congestion window
LAG_THRESHOLD_MS = 50.0    # was 100.0
VERSION_GAP_MAX = 2        # was 3

# Add adaptive bitrate signal
if lag_ms > 80.0:
    # Signal scrcpy to reduce bitrate temporarily
    await self._request_bitrate_reduction(serial)
```

#### 1.4 No TCP_NODELAY on WebSocket
Docker bridge + Nagle's algorithm = extra 40ms delay for small frames.

**Fix (web/server.py or ws.py):**
```python
# When creating WebSocket server
import socket
ws.transport.get_extra_info('socket').setsockopt(
    socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
)
```

#### 1.5 Container Resource Limits
If Docker container doesn't have enough CPU for PyAV JPEG encoding (fallback mode) or H264 parsing, frames back up.

**Fix:**
```yaml
# docker-compose.yml
services:
  farm:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 4G
        reservations:
          cpus: '2.0'
          memory: 2G
```

#### 1.6 gRPC Relay Buffer Tuning
Default gRPC message sizes and flow control windows may be too small, causing unnecessary round-trips.

**Fix (gRPC server options):**
```python
server = grpc.aio.server(options=[
    ('grpc.max_send_message_length', 4 * 1024 * 1024),  # 4MB
    ('grpc.max_receive_message_length', 4 * 1024 * 1024),
    ('grpc.http2.min_recv_ping_interval_without_data_ns', 5_000_000_000),  # 5s
    ('grpc.keepalive_time_ms', 10_000),         # ping every 10s
    ('grpc.keepalive_timeout_ms', 5_000),       # 5s timeout
    ('grpc.keepalive_permit_without_calls', 1),  # ping even when idle
    ('grpc.http2.max_frame_size', 65536),        # larger frames = fewer syscalls
])
```

---

## Problem 2: U2 WebSocket Disconnects

### Root Causes

#### 2.1 Docker Proxy Idle Timeout (BIGGEST CAUSE)
If running behind Nginx/Caddy/Traefik reverse proxy, default idle timeout = **60 seconds**. U2 connections idle between actions → proxy kills them.

**Fix (Nginx):**
```nginx
location /ws {
    proxy_pass http://farm:8081;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;   # 1 hour (was 60s default)
    proxy_send_timeout 3600s;
    proxy_connect_timeout 10s;
}

location /grpc {
    grpc_pass grpc://farm:50051;
    grpc_read_timeout 3600s;
    grpc_send_timeout 3600s;
}
```

**Fix (Traefik):**
```yaml
# traefik dynamic config
http:
  services:
    farm:
      loadBalancer:
        servers:
          - url: "http://farm:8081"
        responseForwarding:
          flushInterval: "10ms"
  middlewares:
    ws-timeout:
      headers:
        customResponseHeaders:
          X-Forwarded-Proto: "ws"
      # Set via CLI: --entrypoints.web.transport.respondingTimeouts.readTimeout=3600s
```

#### 2.2 App-level Ping Disabled (ws_ping_interval = None)
Current code disables WebSocket library ping (`config.py:20`) due to concurrent drain assertion bug. But without ping, intermediary proxies/load balancers WILL kill idle connections.

**Fix — App-level heartbeat already exists (u2_keepalive_loop, 5s interval).** The issue is this heartbeat goes through **u2 HTTP**, not through the **WebSocket** connection itself. The proxy sees the WS as idle.

**Real fix:**
```python
# In ws.py — add WS-level ping on the browser-facing WebSocket
async def _ws_ping_loop(ws, interval=15):
    """Keep WS alive through proxies"""
    try:
        while True:
            await asyncio.sleep(interval)
            pong = await ws.ping()
            await asyncio.wait_for(pong, timeout=10)
    except Exception:
        pass  # connection closed, exit silently
```

#### 2.3 Docker Bridge TCP Keepalive Too Slow
Docker's default `tcp_keepalive_time = 7200s` (2 hours!). Dead connections aren't detected for 2 hours.

**Fix (Dockerfile or docker-compose.yml):**
```yaml
# docker-compose.yml
services:
  farm:
    sysctls:
      net.ipv4.tcp_keepalive_time: 60      # start probes after 60s idle
      net.ipv4.tcp_keepalive_intvl: 10     # probe every 10s
      net.ipv4.tcp_keepalive_probes: 6     # give up after 6 fails
```

#### 2.4 U2 ATX-Agent Crash on Low Memory Devices
atx-agent (port 7912) crashes when Android kills it for memory. Current recovery (`_recover_u2_ws_mode`) has 30s cooldown — too slow for interactive use.

**Fix:**
```python
# Reduce recovery cooldown for atx-agent path
_U2_RECOVERY_COOLDOWN = 10  # was 30s — atx-agent restarts in ~3s

# Add proactive health check before task execution
async def execute_task(self, task):
    await self.ensure_u2_healthy(ping_timeout=2.0)  # fast pre-check
    # ... run task
```

#### 2.5 gRPC Keepalive Through Docker Swarm/Overlay
Known issue: Docker Swarm overlay network doesn't forward gRPC HTTP/2 PING frames properly. Connections silently die after 15 minutes.

**Fix:** If using Docker Swarm, add `DNSRR` endpoint mode:
```yaml
services:
  farm:
    deploy:
      endpoint_mode: dnsrr  # bypass swarm load balancer
```

---

## Quick Win Checklist (Priority Order)

| # | Change | Impact | Effort |
|---|--------|--------|--------|
| 1 | `network_mode: host` in Docker | -10-15ms latency | 1 min |
| 2 | Nginx `proxy_read_timeout 3600s` | Fixes 90% of u2 disconnects | 2 min |
| 3 | TCP keepalive sysctls | Detect dead connections fast | 1 min |
| 4 | Lower scrcpy bitrate to 2Mbps | -20-40ms burst delay | 1 min |
| 5 | WS-level ping loop (15s) | Keep proxy connections alive | 15 min |
| 6 | TCP_NODELAY on WebSocket | -10-40ms for small frames | 5 min |
| 7 | gRPC keepalive options | Prevent silent gRPC death | 10 min |
| 8 | Reduce u2 recovery cooldown | Faster reconnect (30s→10s) | 2 min |
| 9 | Tighter congestion threshold | Earlier frame drop = less queue | 10 min |
| 10 | Container CPU/memory limits | Prevent resource starvation | 2 min |

---

## Architecture-Level Improvements (If Quick Wins Aren't Enough)

### A. Switch to WebRTC for Browser Streaming
Replace WebSocket H264 → WebRTC (WHEP/WHIP protocol). Benefits:
- Built-in congestion control (REMB/TWCC)
- Hardware decode on browser side
- Adaptive bitrate out of the box
- ~100-200ms end-to-end latency

Libraries: [mediasoup](https://mediasoup.org/), [Pion WebRTC (Go)](https://github.com/pion/webrtc)

**Trade-off:** Significant rewrite. Only worth it if managing 50+ concurrent viewers.

### B. Use QUIC/WebTransport Instead of WebSocket
WebTransport provides:
- Multiplexed streams (no head-of-line blocking)
- Unreliable datagrams (perfect for video — drop old frames, no retransmit)
- Built-in congestion control

**Trade-off:** Browser support limited to Chromium. Not ready for production in 2026 Q2.

### C. Frame Pipeline: Zero-Copy with SharedArrayBuffer
For JPEG fallback mode, avoid copying frame bytes through Python. Use shared memory:
```python
import multiprocessing.shared_memory as shm
frame_shm = shm.SharedMemory(name='frame_buffer', create=True, size=1024*1024)
# Write frame directly, reader picks up via mmap
```

---

## Docker-Specific Deployment Recommendations

### Minimal docker-compose.yml
```yaml
version: '3.8'
services:
  farm:
    build: .
    network_mode: host
    restart: unless-stopped
    sysctls:
      net.ipv4.tcp_keepalive_time: 60
      net.ipv4.tcp_keepalive_intvl: 10
      net.ipv4.tcp_keepalive_probes: 6
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 4G
    environment:
      - SCRCPY_BITRATE=2000000
      - SCRCPY_MAX_FPS=15
      - SCRCPY_MAX_WIDTH=480
      - U2_KEEPALIVE_INTERVAL=5
    volumes:
      - ./config.yaml:/app/config.yaml:ro
```

### If Behind Reverse Proxy (Nginx)
```nginx
upstream farm_backend {
    server 127.0.0.1:8081;
    keepalive 32;
}

server {
    listen 80;
    
    location / {
        proxy_pass http://farm_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    location /ws {
        proxy_pass http://farm_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

---

## References

- [scrcpy latency in cloud/Docker setups — Issue #6642](https://github.com/genymobile/scrcpy/issues/6642)
- [ws-scrcpy — WebSocket-based scrcpy client](https://github.com/NetrisTV/ws-scrcpy)
- [uiautomator2 Docker connection issue — Issue #931](https://github.com/openatx/uiautomator2/issues/931)
- [gRPC keepalive docs](https://grpc.io/docs/guides/keepalive/)
- [gRPC streaming keepalive + Docker Swarm — Issue #2549](https://github.com/grpc/grpc-go/issues/2549)
- [WebSocket Architecture Best Practices — Ably](https://ably.com/topic/websocket-architecture-best-practices)
- [Docker WebSocket Configuration Guide (2026)](https://oneuptime.com/blog/post/2026-02-08-how-to-configure-docker-containers-for-websocket-connections/view)
- [gRPC Performance Best Practices — Microsoft](https://learn.microsoft.com/en-us/aspnet/core/grpc/performance)
- [Nginx Ingress WS timeout issue — #5167](https://github.com/kubernetes/ingress-nginx/issues/5167)
- [WINK WebSocket Streaming Analysis 2025](https://www.wink.co/documentation/WINK-WebSocket-Streaming-Analysis-2025)

---

## Unresolved Questions

1. **Reverse proxy setup?** — What's between browser and Docker container? (Nginx, Caddy, Traefik, bare?) This determines the exact timeout fix.
2. **Docker networking mode?** — Currently using bridge or host?
3. **How many concurrent devices?** — If >20, consider splitting gRPC relay into separate container.
4. **Are u2 disconnects on ALL devices or specific ones?** — If specific, likely Android OOM killing atx-agent.
