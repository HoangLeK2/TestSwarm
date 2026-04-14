# Kế hoạch tích hợp Tailscale vào Device Farm

> Ngày tạo: 2026-04-14
> Trạng thái: Draft
> Ưu tiên: High — mở khóa khả năng deploy cloud ↔ local

---

## Mục tiêu

Kết nối **cloud server** (chạy docker-compose: farm, postgres, temporal) với **local PC** (chạy agent-boot + USB Android devices) qua Tailscale mesh VPN, thay thế việc phải expose port public hoặc cùng LAN.

```
┌─────────────────────────────────┐           ┌─────────────────────────────────┐
│ CLOUD SERVER (VPS/EC2)          │           │ LOCAL PC (Mac/Linux)             │
│                                 │ Tailscale │                                 │
│  docker-compose:                │◄─ mesh ──►│  agent-boot (bare metal)         │
│   ├ farm     :8081 + :50051     │  100.x.y  │   └─ ADB → Android devices      │
│   ├ postgres :5432              │           │                                 │
│   ├ temporal :7233              │           │   │
│   └ temporal-ui :8233
|    └ front-end dev :3000
|                                 │           │                                 │
│                                 │           │                                 │
│  tag: cloud-server              │           │  tag: local-agent                │
└─────────────────────────────────┘           └─────────────────────────────────┘
```

---

## Phase 0: Chuẩn bị (30 phút)

### 0.1 Tạo tài khoản Tailscale

- Đăng ký tại [https://login.tailscale.com](https://login.tailscale.com) (dùng Google/GitHub)
- Ghi nhớ tailnet name (VD: `galari.github`)

### 0.2 Tạo auth keys

- Vào Admin Console → Settings → Keys
- Tạo **OAuth client secret** (recommended) hoặc auth key:
  - Permissions: `Devices:Core` (write), `Keys:Auth Keys` (write)
  - Tags: `tag:cloud-server`, `tag:local-agent`
- Lưu key vào `.env` (KHÔNG commit)

### 0.3 Cấu hình ACL

- Vào Admin Console → Access Controls
- Thay default `*:`* bằng policy sau:

```json
{
  "tagOwners": {
    "tag:cloud-server": ["autogroup:admin"],
    "tag:local-agent": ["autogroup:admin"]
  },
  "acls": [
    {
      "action": "accept",
      "src": ["tag:local-agent"],
      "dst": ["tag:cloud-server:8081,50051,8233"]
    },
    {
      "action": "accept",
      "src": ["tag:cloud-server"],
      "dst": ["tag:local-agent:*"]
    },
    {
      "action": "accept",
      "src": ["autogroup:admin"],
      "dst": ["*:*"]
    }
  ],
  "ssh": [
    {
      "action": "accept",
      "src": ["autogroup:admin"],
      "dst": ["tag:cloud-server"],
      "users": ["autogroup:nonroot", "root"]
    }
  ],
  "tests": [
    {
      "src": "tag:local-agent",
      "accept": ["tag:cloud-server:50051"],
      "deny":   ["tag:cloud-server:5432"]
    }
  ]
}
```

**Giải thích**:

- agent-boot → farm: chỉ port 8081 (API/WS) + 50051 (gRPC relay) + 8233 (Temporal UI)
- farm → agent-boot: mọi port (cần cho health check, push commands)
- admin (bạn): full access + SSH
- PostgreSQL (5432) **KHÔNG** expose cho agent — chỉ internal docker network

---

## Phase 1: Cloud Server — Tailscale sidecar trong Docker (1 giờ)

### 1.1 Thêm Tailscale sidecar vào docker-compose.yml

```yaml
services:
  # ── Tailscale VPN sidecar ──────────────────────────────────
  tailscale:
    image: tailscale/tailscale:latest
    hostname: device-farm-cloud
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_EXTRA_ARGS=--advertise-tags=tag:cloud-server
      - TS_USERSPACE=false
    volumes:
      - ts-state:/var/lib/tailscale
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    devices:
      - /dev/net/tun:/dev/net/tun
    restart: unless-stopped

  # farm service — share network with tailscale
  farm:
    # ... existing config ...
    network_mode: service:tailscale  # <-- THÊM DÒNG NÀY
    depends_on:
      tailscale:            # <-- THÊM
        condition: service_started
      postgres:
        condition: service_healthy
      temporal:
        condition: service_healthy

volumes:
  ts-state:          # <-- THÊM
  pgdata:
  farm_captures:
```

### 1.2 Cập nhật .env

```bash
# .env (root project)
TS_AUTHKEY=tskey-client-XXXXX?ephemeral=false

# Existing vars...
DB_PASSWORD=postgres
RELAY_API_KEY=your-relay-key
```

### 1.3 Xử lý port mapping

**Quan trọng**: Khi farm dùng `network_mode: service:tailscale`, port mapping phải chuyển sang tailscale service:

```yaml
  tailscale:
    # ... existing ...
    ports:                    # <-- Port mapping chuyển về đây
      - "8081:8081"
      - "50051:50051"

  farm:
    # ports: ← XÓA khỏi farm (đã chuyển sang tailscale)
    network_mode: service:tailscale
```

### 1.4 Postgres + Temporal giữ network riêng

Postgres và Temporal **KHÔNG** cần Tailscale — chỉ cần internal Docker network:

```yaml
  postgres:
    # giữ nguyên, KHÔNG thêm network_mode
    # farm truy cập postgres qua docker DNS: postgres:5432

  temporal:
    # giữ nguyên
    # farm truy cập temporal qua docker DNS: temporal:7233
```

**Vấn đề**: Khi farm dùng `network_mode: service:tailscale`, nó rời default bridge network → không resolve được `postgres`, `temporal` qua Docker DNS.

**Giải pháp**: Dùng explicit network:

```yaml
networks:
  internal:
    driver: bridge

services:
  tailscale:
    networks:
      - internal
    # KHÔNG dùng network_mode ở đây

  postgres:
    networks:
      - internal

  temporal:
    networks:
      - internal

  farm:
    network_mode: service:tailscale  # ← chia sẻ network stack với tailscale
    # farm tự động có cả internal network (qua tailscale container)
```

> **Lưu ý**: `network_mode: service:X` kế thừa toàn bộ network config của container X. Nên tailscale container cần join `internal` network để farm vẫn resolve được postgres/temporal.

### 1.5 Verify

```bash
# Deploy
docker compose up -d

# Check tailscale connected
docker compose exec tailscale tailscale status
# Phải thấy: device-farm-cloud  100.x.y.z  linux  ...

# Check farm accessible qua tailscale IP
curl http://100.x.y.z:8081/api/health
```

---

## Phase 2: Local PC — Cài Tailscale native (15 phút)

### 2.1 Cài đặt

```bash
# macOS
brew install --cask tailscale
# Mở Tailscale.app → Sign in cùng account

# Hoặc Linux (nếu local PC là Linux)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --advertise-tags=tag:local-agent
```

### 2.2 Verify kết nối

```bash
tailscale status
# Phải thấy cả device-farm-cloud và local PC

tailscale ping device-farm-cloud
# pong from device-farm-cloud (100.x.y.z) via <ip>:41641 in 15ms  ← DIRECT ✅
# Nếu thấy "via DERP" → xem Phase 5 troubleshooting
```

### 2.3 Chạy agent-boot qua Tailscale

```bash
cd agent-boot

# gRPC mode — dùng Tailscale hostname/IP thay vì public IP
RELAY_MODE=grpc uv run main.py \
  --relay-server device-farm-cloud:50051 \
  --relay-api-key <KEY>

# Hoặc WebSocket mode (legacy)
uv run main.py \
  --relay-server ws://device-farm-cloud:8081/relay-agent \
  --relay-api-key <KEY>
```

**Thay đổi duy nhất**: `<host>:50051` → `device-farm-cloud:50051` (MagicDNS hostname)

---

## Phase 3: Cập nhật config.yaml (10 phút)

### 3.1 Thêm section tailscale

```yaml
# config.yaml — thêm vào cuối file
tailscale:
  enabled: true
  cloud_hostname: "device-farm-cloud"   # MagicDNS hostname
  local_hostname: "local-agent"         # MagicDNS hostname
```

### 3.2 Relay config — không đổi

```yaml
relay:
  enabled: true
  port: 50051
  api_key: ""   # vẫn set qua RELAY_API_KEY env var
```

gRPC relay hoạt động bình thường qua Tailscale — transparent. Không cần thay đổi code relay.

---

## Phase 4: Cloud firewall hardening (15 phút)

### 4.1 Mở port cho Tailscale direct connection

```bash
# AWS Security Group
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxx \
  --protocol udp --port 41641 --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
  --group-id sg-xxx \
  --protocol udp --port 3478 --cidr 0.0.0.0/0
```

### 4.2 Đóng port public không cần thiết

```bash
# Giữ lại:
# - TCP 443 (HTTPS nếu cần web access public)
# - UDP 41641 + 3478 (Tailscale)

# Xóa/đóng:
# - TCP 8081 (farm API — giờ qua Tailscale)
# - TCP 50051 (gRPC relay — giờ qua Tailscale)
# - TCP 8233 (Temporal UI — giờ qua Tailscale)
# - TCP 5433 (PostgreSQL — giờ chỉ internal Docker)
```

### 4.3 Giữ Public IP trên VM

**Quan trọng**: VM phải có public IP để Tailscale direct connection. Nếu VM sau NAT Gateway → bị ép dùng DERP relay (chậm).

---

## Phase 5: Troubleshooting checklist


| Triệu chứng                        | Kiểm tra                                             | Cách xử lý                                          |
| ---------------------------------- | ---------------------------------------------------- | --------------------------------------------------- |
| `tailscale ping` thấy `via DERP`   | `tailscale netcheck` → check `MappingVariesByDestIP` | Gán public IP cho cloud VM, mở UDP 41641            |
| agent-boot không connect được farm | `curl http://device-farm-cloud:8081/api/health`      | Check farm container running, tailscale status      |
| farm không resolve `postgres`      | `docker compose exec tailscale ping postgres`        | Đảm bảo tailscale container join `internal` network |
| Container mất identity sau restart | Check volume mount                                   | Đảm bảo `ts-state` volume mapped đúng               |
| Timeout gRPC                       | Latency quá cao qua DERP                             | Cần public IP hoặc peer relay                       |


### Debug commands

```bash
# Trên cloud
docker compose exec tailscale tailscale status
docker compose exec tailscale tailscale netcheck
docker compose exec tailscale tailscale ping local-agent

# Trên local
tailscale status
tailscale ping device-farm-cloud
tailscale netcheck
```

---

## Phase 6: Production hardening (sau khi Phase 1-4 hoạt động)

### 6.1 Chuyển sang OAuth client secret

- Thay `tskey-auth-xxx` bằng `tskey-client-xxx` trong `.env`
- Đảm bảo tag advertise đúng

### 6.2 Tắt key expiry cho cloud server

- Admin Console → Machines → device-farm-cloud → Disable key expiry

### 6.3 Bật auto-update

```bash
docker compose exec tailscale tailscale set --auto-update
```

### 6.4 Bật Tailscale SSH (thay thế SSH key management)

```bash
docker compose exec tailscale tailscale set --ssh
# Từ local: tailscale ssh device-farm-cloud
```

### 6.5 Monitoring

- Set up webhook cho configuration changes
- Monitor `tailscale status` trong health check script
- Alert khi connection type chuyển từ direct → DERP

### 6.6 Backup

- Backup `ts-state` Docker volume
- Lưu OAuth client ID/secret ở password manager
- Document recovery procedure

---

## Tổng kết thay đổi code


| File                 | Thay đổi                                           | Effort    |
| -------------------- | -------------------------------------------------- | --------- |
| `docker-compose.yml` | Thêm tailscale service, `network_mode`, networks   | **Chính** |
| `.env`               | Thêm `TS_AUTHKEY`                                  | 1 dòng    |
| `config.yaml`        | Thêm section `tailscale` (optional, informational) | 3 dòng    |
| `.gitignore`         | Đảm bảo `.env` đã có                               | Check     |
| agent-boot CLI args  | Thay hostname → MagicDNS name                      | 1 flag    |
| **Code Python**      | **KHÔNG thay đổi**                                 | 0         |


### Điểm quan trọng nhất

> **Không cần thay đổi code Python**. Tailscale là network-level VPN — transparent cho ứng dụng. gRPC, WebSocket, HTTP đều hoạt động bình thường. Chỉ thay đổi infrastructure (docker-compose + DNS hostname).

---

## Timeline ước tính


| Phase                 | Thời gian    | Ghi chú                              |
| --------------------- | ------------ | ------------------------------------ |
| Phase 0: Chuẩn bị     | 30 phút      | Account, keys, ACL                   |
| Phase 1: Cloud Docker | 1 giờ        | docker-compose changes, test         |
| Phase 2: Local PC     | 15 phút      | Install + verify                     |
| Phase 3: Config       | 10 phút      | config.yaml + agent-boot args        |
| Phase 4: Firewall     | 15 phút      | Security group changes               |
| Phase 5: Test E2E     | 30 phút      | Full flow: agent-boot → relay → farm |
| Phase 6: Hardening    | Khi ổn định  | OAuth, SSH, monitoring               |
| **Tổng (Phase 0-5)**  | **~2.5 giờ** | Đủ để có working setup               |


---

## Rủi ro & Mitigation


| Rủi ro                       | Xác suất   | Impact                           | Mitigation                                           |
| ---------------------------- | ---------- | -------------------------------- | ---------------------------------------------------- |
| DERP relay (không direct)    | Trung bình | Latency cao → gRPC timeout       | Public IP + mở UDP 41641                             |
| Docker network_mode conflict | Thấp       | farm mất kết nối postgres        | Test kỹ Phase 1.4 (explicit network)                 |
| Tailscale service downtime   | Rất thấp   | Mất kết nối mesh                 | Container auto-restart + DERP fallback               |
| Auth key leak                | Thấp       | Unauthorized device join tailnet | OAuth secret + `.env` in `.gitignore` + ACL restrict |


