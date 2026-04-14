# Research Report: Tailscale — Cloud Server ↔ Local PC Connectivity

## Bảng tổng hợp tiếng Việt

### 1. Tailscale là gì?


| Mục                | Chi tiết                                                               |
| ------------------ | ---------------------------------------------------------------------- |
| **Loại**           | Mesh VPN dựa trên WireGuard                                            |
| **Cách hoạt động** | Mỗi device nhận IP cố định `100.x.y.z`, kết nối P2P trực tiếp qua NAT  |
| **Mã hóa**         | End-to-end WireGuard (coordination server KHÔNG thấy nội dung traffic) |
| **NAT traversal**  | Tự động, thành công >90%. Thất bại → fallback qua DERP relay           |
| **DNS**            | MagicDNS tự gán hostname (VD: `my-server.tailnet.ts.net`)              |
| **Xác thực**       | Qua identity provider (Google, GitHub, Microsoft)                      |


### 2. Hiệu năng


| Loại kết nối             | Latency thêm | Throughput                                        |
| ------------------------ | ------------ | ------------------------------------------------- |
| Direct (cùng region)     | <1ms         | Tối đa tốc độ WAN (>10Gbps trên bare metal Linux) |
| Direct (khác region)     | +0.5–2ms     | Tối đa tốc độ WAN                                 |
| DERP relay (cùng region) | +10–30ms     | ~35 Mbps (worst case)                             |
| DERP relay (khác region) | +30–80ms     | ~35 Mbps (worst case)                             |


> **Lưu ý**: AWS/GCP NAT Gateway = "hard NAT" → ép dùng DERP relay. **Gán public IP cho VM** để có direct connection.

### 3. So sánh với các giải pháp khác


| Tiêu chí               | **Tailscale**                         | **WireGuard (thủ công)**             | **Cloudflare Tunnel**                        | **ZeroTier**                 |
| ---------------------- | ------------------------------------- | ------------------------------------ | -------------------------------------------- | ---------------------------- |
| **Kiến trúc**          | Mesh VPN                              | P2P VPN (kernel)                     | Reverse proxy                                | Mesh VPN                     |
| **Độ khó setup**       | Rất dễ (đăng nhập SSO)                | Khó (cấu hình key, IP thủ công)      | Trung bình (cấu hình app)                    | Dễ (web UI)                  |
| **NAT traversal**      | Tự động (>90%)                        | Phải forward port thủ công           | Không cần (outbound only)                    | Tự động                      |
| **Hiệu năng**          | Gần bằng WireGuard                    | Tốt nhất (kernel-level)              | +15–45ms qua edge                            | Chậm hơn (userspace)         |
| **Bảo mật**            | E2E, Tailscale không thấy data        | E2E, toàn quyền kiểm soát            | **Cloudflare thấy traffic** (terminates TLS) | E2E                          |
| **Expose ra internet** | Funnel (giới hạn port 443,8443,10000) | Tự cấu hình                          | Mục đích chính                               | Không hỗ trợ                 |
| **Tự host**            | Không (control plane của Tailscale)   | Hoàn toàn                            | Không                                        | Có (root servers)            |
| **Free tier**          | 100 devices, 3–6 users                | Miễn phí (open source)               | 50 users, unlimited tunnels                  | 25 devices                   |
| **Phù hợp nhất**       | Mesh nội bộ, team nhỏ-vừa             | Kiểm soát tối đa, mạng cố định       | Expose service ra public                     | Mạng phức tạp, cần L2        |
| **Cho Device Farm?**   | **Phù hợp nhất**                      | Phù hợp nếu chấp nhận setup phức tạp | Chỉ phù hợp nếu cần public access            | Thay thế được nhưng chậm hơn |


### 4. Bảo mật


| Thành phần          | Thấy gì?                          | Rủi ro                                                |
| ------------------- | --------------------------------- | ----------------------------------------------------- |
| Coordination server | Metadata, public keys, ACL config | Không thấy nội dung. Lý thuyết có thể inject node giả |
| DERP relay          | Packet WireGuard đã mã hóa        | Không giải mã được. Thấy src/dst IP                   |
| Device của bạn      | Mọi thứ (giải mã tại đây)         | Bảo mật endpoint thông thường                         |



| Tính năng bảo mật  | Mô tả                                                       | Cần thiết?                        |
| ------------------ | ----------------------------------------------------------- | --------------------------------- |
| **ACL**            | Kiểm soát device nào truy cập port nào                      | **Bắt buộc** — thay default `*:*` |
| **Tailnet Lock**   | Ký cryptographic cho mọi node — loại bỏ trust vào Tailscale | Chỉ cho high-security             |
| **Tailscale SSH**  | SSH không cần key, xác thực qua Tailscale identity          | Khuyến nghị                       |
| **Device posture** | Kiểm tra trạng thái thiết bị trước cho phép kết nối         | Paid plan only                    |


### 5. Docker Integration


| Pattern                | Mô tả                                                                                        | Khi nào dùng                        |
| ---------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------- |
| **Sidecar**            | 1 container Tailscale + 1 container app, chia sẻ network (`network_mode: service:tailscale`) | Khuyến nghị mặc định                |
| `**tailscale serve`**  | HTTPS reverse proxy nội bộ tailnet với auto cert                                             | Web service nội bộ                  |
| `**tailscale funnel**` | Expose ra internet public                                                                    | Webhook, demo                       |
| **TSDProxy**           | 1 reverse proxy cho nhiều service (thay vì 1 sidecar/service)                                | Nhiều service, tiết kiệm tài nguyên |



| Cấu hình Docker   | Giá trị                                  | Ghi chú                                                     |
| ----------------- | ---------------------------------------- | ----------------------------------------------------------- |
| `TS_AUTHKEY`      | `tskey-auth-xxx` hoặc `tskey-client-xxx` | OAuth client secret (`tskey-client`) tốt hơn cho production |
| `TS_STATE_DIR`    | `/var/lib/tailscale`                     | **BẮT BUỘC mount volume** — mất state = mất identity        |
| `TS_EXTRA_ARGS`   | `--advertise-tags=tag:xxx`               | Gán tag cho ACL                                             |
| `TS_SERVE_CONFIG` | `/config/serve.json`                     | Cấu hình serve tự động                                      |
| `cap_add`         | `NET_ADMIN`, `SYS_MODULE`                | Cần cho tạo tunnel                                          |
| `devices`         | `/dev/net/tun`                           | Cần cho WireGuard                                           |


### 6. Cloud setup


| Cloud     | Cách lấy Public IP                                              | Firewall rules cần mở       |
| --------- | --------------------------------------------------------------- | --------------------------- |
| **AWS**   | Elastic IP, đặt VM ở **public subnet** (không dùng NAT Gateway) | UDP 41641, UDP 3478 inbound |
| **GCP**   | External IP trên VM NIC. Hoặc bật Endpoint-Independent Mapping  | UDP 41641, UDP 3478 inbound |
| **Azure** | Public IP resource gắn vào NIC                                  | UDP 41641, UDP 3478 inbound |


### 7. Free tier


| Tính năng      | Giới hạn     | Đủ cho Device Farm? |
| -------------- | ------------ | ------------------- |
| Số users       | 3–6          | Đủ                  |
| Số devices     | 100          | Đủ                  |
| Subnet routers | Có           | Đủ                  |
| MagicDNS       | Có           | Đủ                  |
| ACL            | Có           | Đủ                  |
| Tailscale SSH  | Có           | Đủ                  |
| Serve & Funnel | Có           | Đủ                  |
| HTTPS certs    | Có           | Đủ                  |
| SSO/SAML       | Không (paid) | Không cần           |
| Audit logging  | Không (paid) | Không cần           |


### 8. Checklist triển khai


| Bước | Hành động                 | Lệnh / Ghi chú                                                              |
| ---- | ------------------------- | --------------------------------------------------------------------------- |
| 1    | Đăng ký Tailscale         | [login.tailscale.com](https://login.tailscale.com) — dùng Google/GitHub     |
| 2    | Tạo auth key              | Admin Console → Settings → Keys → Generate                                  |
| 3    | Cài trên Cloud (Ubuntu)   | `curl -fsSL https://tailscale.com/install.sh | sh`                          |
| 4    | Kết nối Cloud (headless)  | `sudo tailscale up --auth-key=tskey-auth-XXX --advertise-tags=tag:cloud`    |
| 5    | Cài trên Mac              | `brew install --cask tailscale` → Mở app → Sign in                          |
| 6    | Xác nhận kết nối          | `tailscale ping cloud-server` — phải thấy `via <ip>` (DIRECT)               |
| 7    | Test gọi service          | `curl http://cloud-server:8080` từ Mac                                      |
| 8    | Cấu hình ACL              | Admin Console → Access Controls → Thay `*:`* bằng rules cụ thể              |
| 9    | Đóng public ports         | Xóa rules SSH/HTTP public trên cloud firewall — truy cập qua Tailscale only |
| 10   | Tắt key expiry cho server | Admin Console → Machines → Disable key expiry                               |
| 11   | Bật auto-update           | `tailscale set --auto-update`                                               |


### 9. Lệnh hay dùng


| Lệnh                                      | Mô tả                            |
| ----------------------------------------- | -------------------------------- |
| `tailscale up`                            | Kết nối vào tailnet              |
| `tailscale down`                          | Ngắt kết nối                     |
| `tailscale status`                        | Xem tất cả devices và trạng thái |
| `tailscale ping <host>`                   | Kiểm tra direct hay relay        |
| `tailscale netcheck`                      | Chẩn đoán NAT type, latency, UDP |
| `tailscale ip -4`                         | Xem IP Tailscale của mình        |
| `tailscale ssh <host>`                    | SSH không cần key                |
| `tailscale serve <port>`                  | HTTPS nội bộ tailnet             |
| `tailscale funnel <port>`                 | Expose ra internet               |
| `tailscale set --advertise-routes=<CIDR>` | Quảng bá subnet route            |
| `tailscale set --hostname=<name>`         | Đổi hostname MagicDNS            |
| `tailscale update`                        | Cập nhật phiên bản               |


### 10. Lỗi thường gặp & cách xử lý


| Triệu chứng                        | Nguyên nhân                  | Cách xử lý                                 |
| ---------------------------------- | ---------------------------- | ------------------------------------------ |
| Mọi kết nối qua DERP (chậm)        | VM sau NAT Gateway (AWS/GCP) | Gán public IP cho VM                       |
| `MappingVariesByDestIP: true`      | Symmetric NAT                | Public IP hoặc peer relay                  |
| `UDP: false` trong netcheck        | Firewall chặn UDP            | Mở UDP 41641 outbound                      |
| Kết nối tự ngắt định kỳ            | Key hết hạn                  | Tắt key expiry cho server                  |
| Docker container không kết nối     | Thiếu quyền                  | Thêm `cap_add: NET_ADMIN` + `/dev/net/tun` |
| Mất identity sau restart container | Không mount state volume     | Mount volume cho `TS_STATE_DIR`            |
| Throughput thấp trên Linux         | Chưa bật UDP GRO             | `ethtool -K eth0 rx-udp-gro-forwarding on` |


---

*Phần dưới đây là report chi tiết bằng tiếng Anh.*

---

> Research date: 2026-04-14 | Sources: 5 search rounds, 40+ sources

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture & How It Works](#architecture--how-it-works)
3. [Performance Benchmarks](#performance-benchmarks)
4. [Security Deep Dive](#security-deep-dive)
5. [Docker Integration](#docker-integration)
6. [Cloud-Specific Guidance (AWS/GCP/Azure)](#cloud-specific-guidance)
7. [NAT Traversal & Troubleshooting](#nat-traversal--troubleshooting)
8. [Comparison: Tailscale vs Alternatives](#comparison-tailscale-vs-alternatives)
9. [Production Deployment Checklist](#production-deployment-checklist)
10. [Implementation Recommendations](#implementation-recommendations)
11. [Resources & References](#resources--references)

---

## Executive Summary

Tailscale is a mesh VPN built on WireGuard that creates an encrypted overlay network (tailnet) where every device gets a stable `100.x.y.z` IP. It handles NAT traversal automatically with >90% direct connection success rate. For the Device Farm use case (cloud server ↔ local Mac with Android devices), Tailscale is the **recommended choice** — zero-config, free tier sufficient (100 devices), sub-millisecond overhead on direct connections.

Key findings:

- **Performance**: Direct connections add <1ms latency over raw WireGuard. Throughput exceeds 10Gbps on Linux bare metal. DERP relay fallback drops to ~35 Mbps worst case.
- **Security**: End-to-end WireGuard encryption. Coordination server sees metadata only. Tailnet Lock removes trust in Tailscale infrastructure entirely.
- **Docker**: Official sidecar pattern with `TS_AUTHKEY` env var. State persistence via volumes. OAuth client secrets preferred over auth keys for production.
- **Cloud gotcha**: AWS/GCP NAT Gateways are "hard NAT" — forces DERP relay. **Use public IPs on cloud VMs** for direct connections.

---

## Architecture & How It Works

```
┌──────────────┐        Tailscale Coordination Server        ┌──────────────┐
│ Cloud Server │  ←── key exchange, peer discovery, ACLs ──→ │  Local Mac   │
│ 100.64.0.1   │                                             │ 100.64.0.2   │
└──────┬───────┘                                             └──────┬───────┘
       │                                                            │
       │              Direct WireGuard UDP tunnel                   │
       │◄──────────────── (peer-to-peer) ─────────────────────────►│
       │                                                            │
       │         ┌─────────────────────┐                            │
       │         │   DERP Relay        │  ← fallback only          │
       │◄───────►│   (if NAT blocks)   │◄─────────────────────────►│
       │         └─────────────────────┘                            │
```

### Connection lifecycle:

1. Device authenticates via identity provider (Google/GitHub/etc)
2. Coordination server distributes public keys and peer info
3. Clients attempt direct UDP connection via NAT traversal (STUN + port mapping)
4. If direct fails → fallback to DERP relay (encrypted, Tailscale can't see data)
5. Periodically retries direct connection upgrade

### Key concepts:

- **Tailnet**: Your private network. All devices sharing same account = same tailnet
- **MagicDNS**: Auto hostname resolution (`my-server.tailnet-name.ts.net`)
- **DERP**: Designated Encrypted Relay Protocol — fallback when P2P fails
- **ACLs**: Access Control Lists enforced at destination device, not coordination server
- **Tailnet Lock**: Cryptographic node signing — removes trust in coordination server

---

## Performance Benchmarks

### Latency overhead


| Connection type                  | Additional latency | Notes                              |
| -------------------------------- | ------------------ | ---------------------------------- |
| Direct (same region)             | **<1ms**           | Nearly identical to raw WireGuard  |
| Direct (cross-region)            | **+0.5-2ms**       | WireGuard encryption overhead only |
| DERP relay (same region)         | **+10-30ms**       | Routed through nearest relay       |
| DERP relay (cross-region)        | **+30-80ms**       | Depends on relay proximity         |
| Cloudflare Tunnel (comparison)   | **+15-45ms**       | Routes through Cloudflare edge     |
| Nginx reverse proxy (comparison) | **+2-8ms**         | Direct connection proxy            |


### Throughput


| Scenario                                 | Throughput                                        |
| ---------------------------------------- | ------------------------------------------------- |
| Linux bare metal (optimized)             | **>10 Gbps** (wireguard-go with UDP segmentation) |
| AWS EC2 c6i.8xlarge                      | **~7.3 Gbps** (limited by AWS underlay)           |
| AWS EC2 single-flow (no placement group) | **5 Gbps max** (AWS limit)                        |
| DERP relay (stress test worst case)      | **~35 Mbps**                                      |
| Typical home/office direct               | **Limited by WAN upload speed**                   |


### Performance tuning (Linux subnet routers/exit nodes)

```bash
# Enable UDP GRO forwarding
NETDEV=$(ip -o route get 8.8.8.8 | cut -f 5 -d " ")
sudo ethtool -K $NETDEV rx-udp-gro-forwarding on rx-gro-list off

# Limit C-States for lower latency (forwarding nodes)
# Add to kernel boot params: intel_idle.max_cstate=1
```

**Hardware recommendation**: Higher CPU clock speed matters more than core count for Tailscale forwarding nodes.

---

## Security Deep Dive

### Threat model


| Component               | What it sees                             | Risk                                                               |
| ----------------------- | ---------------------------------------- | ------------------------------------------------------------------ |
| **Coordination server** | Device metadata, public keys, ACL config | Cannot see traffic content. Could theoretically inject rogue nodes |
| **DERP relays**         | Encrypted WireGuard packets              | Cannot decrypt. Metadata (src/dst IP) visible                      |
| **Your device**         | Everything decrypted                     | Standard endpoint security applies                                 |


### Tailnet Lock — Remove coordination server trust

Tailnet Lock requires user-controlled cryptographic signatures for all node keys distributed by the coordination server. Even if Tailscale is compromised, attacker cannot add nodes to your tailnet.

**Trade-off**: Operational overhead — need hardened signing nodes, manual device approval process, recovery plan if signing nodes become unavailable. **Recommended for**: High-security environments. **Not needed for**: Most dev/lab setups.

### ACL best practices

```json
{
  "groups": {
    "group:cloud": ["tag:cloud-server"],
    "group:local": ["tag:local-pc"]
  },
  "acls": [
    // Cloud → Local: only specific service ports
    {"action": "accept", "src": ["tag:cloud-server"], "dst": ["tag:local-pc:8080,9008"]},
    // Local → Cloud: DB + API
    {"action": "accept", "src": ["tag:local-pc"], "dst": ["tag:cloud-server:5432,8080,443"]},
    // Block everything else (implicit deny)
  ],
  "tests": [
    {"src": "tag:cloud-server", "accept": ["tag:local-pc:8080"]},
    {"src": "tag:cloud-server", "deny": ["tag:local-pc:22"]},
    {"src": "tag:local-pc", "accept": ["tag:cloud-server:5432"]},
  ]
}
```

### Recent security bulletins (2025)

- Subnet router shared between tailnets didn't enforce protocol filters in ACLs — **patched**
- DERP mesh auth used non-constant-time comparison (timing side-channel) — **patched May 2025**
- Regular audits by Latacora + automated static analysis + dependency vulnerability scans

### Hardening checklist

- Replace default `*:`* ACL with explicit port-specific rules
- Add ACL deny tests for critical paths (production DB)
- Set up webhooks for configuration change alerts
- Enable device posture checks (if on paid plan)
- Consider Tailnet Lock for high-security environments
- Use auth keys with expiry, prefer one-time over reusable
- Close public ports on cloud firewalls — access via Tailscale only
- Enable 2FA on identity provider

---

## Docker Integration

### Pattern 1: Sidecar (recommended)

```yaml
# docker-compose.yml
services:
  tailscale:
    image: tailscale/tailscale:latest
    hostname: my-service
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_EXTRA_ARGS=--advertise-tags=tag:container
    volumes:
      - tailscale-state:/var/lib/tailscale
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    devices:
      - /dev/net/tun:/dev/net/tun
    restart: unless-stopped

  app:
    image: my-app:latest
    network_mode: service:tailscale  # <-- shares tailscale's network
    depends_on:
      - tailscale

volumes:
  tailscale-state:
```

### Pattern 2: With `tailscale serve` (HTTPS)

```yaml
services:
  tailscale:
    image: tailscale/tailscale:latest
    hostname: my-app
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_SERVE_CONFIG=/config/serve.json  # auto-configure serve
    volumes:
      - tailscale-state:/var/lib/tailscale
      - ./serve.json:/config/serve.json:ro
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
```

```json
// serve.json
{
  "TCP": {
    "443": {
      "HTTPS": true
    }
  },
  "Web": {
    "my-app.tailnet-name.ts.net:443": {
      "Handlers": {
        "/": {
          "Proxy": "http://127.0.0.1:8080"
        }
      }
    }
  }
}
```

### Auth key best practices

```bash
# .env file (never commit!)
# Option A: Auth key (simpler, expires)
TS_AUTHKEY=tskey-auth-xxxxx

# Option B: OAuth client secret (recommended for production, auto-rotates)
TS_AUTHKEY=tskey-client-xxxxx

# Make node persistent (survives container restart)
TS_AUTHKEY=tskey-client-xxxxx?ephemeral=false
```

**OAuth > Auth keys** for production: OAuth client secrets auto-generate auth keys behind the scenes and don't expire. Need "Devices:Core" and "Keys:Auth Keys" write permissions.

### Key gotchas

- **MUST mount `TS_STATE_DIR` as volume** — otherwise loses config on restart
- `network_mode: service:tailscale` = both containers share network stack
- One sidecar per service for isolation
- Alternative: [TSDProxy](https://github.com/almeidapaulopt/tsdproxy) — single reverse proxy instead of per-service sidecar

---

## Cloud-Specific Guidance

### The AWS/GCP NAT Problem

**Critical**: AWS NAT Gateway and GCP Cloud NAT are "symmetric NAT" (hard NAT). Devices behind them **cannot establish direct P2P connections** → forced to use DERP relay → higher latency, lower throughput.

```
                  ❌ Direct P2P fails
Cloud VM ──► AWS NAT GW ──✗──► Home Router ◄── Local Mac
                  │                                │
                  └──► DERP Relay (slow) ◄─────────┘
```

### Solution: Use Public IPs

```
                  ✅ Direct P2P works
Cloud VM (public IP) ◄──────── Direct UDP ──────────► Local Mac
                        (fast, <1ms overhead)
```


| Cloud     | How to get public IP                                                                   |
| --------- | -------------------------------------------------------------------------------------- |
| **AWS**   | Elastic IP on EC2 instance. Put instance in **public subnet**, not behind NAT Gateway  |
| **GCP**   | External IP on VM NIC. Or use static port allocation with Endpoint-Independent Mapping |
| **Azure** | Public IP resource attached to NIC                                                     |


### Security Group / Firewall Rules

```
# AWS Security Group
Inbound:  UDP 41641 from 0.0.0.0/0   (WireGuard direct connections)
Inbound:  UDP 3478  from 0.0.0.0/0   (STUN)

# GCP Firewall Rule
gcloud compute firewall-rules create tailscale-direct \
  --allow=udp:41641,udp:3478 \
  --target-tags=tailscale
```

### Peer Relays (new, Oct 2025)

Alternative to DERP — designate your own tailnet nodes as relays. Uses native WireGuard UDP (faster than DERP's HTTPS/WebSocket encapsulation). Good for when you can't use public IPs.

```bash
# On a node with public IP, enable peer relay:
sudo tailscale set --advertise-connector
```

### Connection priority order

1. **Direct** — NAT traversal succeeds, WireGuard tunnel
2. **Peer Relay** — your designated relay node
3. **DERP** — Tailscale's public relay infrastructure

---

## NAT Traversal & Troubleshooting

### Diagnosing connection type

```bash
# Check if connection is direct or relayed
tailscale ping my-cloud-server
# pong from my-cloud-server (100.64.0.1) via 203.0.113.5:41641 in 12ms  ← DIRECT ✅
# pong from my-cloud-server (100.64.0.1) via DERP(tok) in 45ms          ← RELAYED ❌

# Full network diagnostics
tailscale netcheck
# Look for:
#   MappingVariesByDestIP: true   ← symmetric NAT, P2P will fail
#   UDP: true                     ← UDP works, good
#   IPv4: yes                     ← has IPv4 connectivity

# Check all peer connections
tailscale status
```

### Common issues & fixes


| Symptom                        | Cause                                 | Fix                                        |
| ------------------------------ | ------------------------------------- | ------------------------------------------ |
| All connections via DERP       | Behind symmetric NAT (AWS/GCP NAT GW) | Use public IP on cloud VM                  |
| `MappingVariesByDestIP: true`  | Symmetric NAT detected                | Public IP or peer relay                    |
| `UDP: false`                   | UDP blocked by firewall               | Open UDP 41641 outbound                    |
| Connection drops periodically  | Key expiry                            | Disable key expiry for servers             |
| Slow throughput on Linux       | UDP GRO not enabled                   | `ethtool -K eth0 rx-udp-gro-forwarding on` |
| Barracuda/Cisco firewall       | Corporate firewall blocks UDP         | Increase max UDP sessions / DERP only mode |
| Docker container can't connect | Missing `NET_ADMIN` capability        | Add `cap_add: NET_ADMIN` + `/dev/net/tun`  |


### Useful debug commands

```bash
tailscale netcheck          # NAT type, DERP latency, UDP availability
tailscale ping <host>       # Direct vs relayed check
tailscale status            # All peers and connection state
tailscale debug prefs       # Current client preferences
tailscale bugreport         # Generate debug bundle for support
journalctl -u tailscaled    # Linux daemon logs
```

---

## Comparison: Tailscale vs Alternatives


|                        | **Tailscale**              | **WireGuard (manual)**       | **Cloudflare Tunnel**       | **ZeroTier**          |
| ---------------------- | -------------------------- | ---------------------------- | --------------------------- | --------------------- |
| **Architecture**       | Mesh VPN (WireGuard)       | P2P VPN (kernel)             | Reverse proxy               | Mesh VPN (custom)     |
| **Setup complexity**   | Minimal (SSO login)        | High (manual keys, IPs)      | Medium (app-level config)   | Low (web UI)          |
| **NAT traversal**      | Auto (>90% success)        | Manual port forwarding       | N/A (outbound only)         | Auto (hole punching)  |
| **Performance**        | Near-WireGuard speed       | Best (kernel-level)          | +15-45ms via edge           | Slower (userspace)    |
| **Encryption**         | WireGuard E2E              | WireGuard E2E                | TLS (Cloudflare terminates) | Custom E2E            |
| **Traffic visibility** | Zero (E2E encrypted)       | Zero                         | **Cloudflare can see**      | Zero                  |
| **Public exposure**    | Funnel (limited ports)     | Manual                       | Native (primary use)        | No                    |
| **Layer**              | L3 (IP)                    | L3 (IP)                      | L7 (HTTP/TCP)               | L2+L3                 |
| **Self-hostable**      | Control plane: no          | Fully                        | No                          | Yes (root servers)    |
| **Free tier**          | 100 devices, 3-6 users     | Free (open source)           | 50 users, unlimited tunnels | 25 devices            |
| **Best for**           | Internal mesh, team access | Max control, static networks | Public-facing services      | Complex L2 topologies |


### Recommendation for Device Farm

**Tailscale** is the best fit because:

1. Need private mesh between cloud and local — not public exposure
2. Zero-config NAT traversal — local PC likely behind home router
3. Free tier covers the use case entirely
4. Docker sidecar pattern fits containerized services
5. MagicDNS simplifies service discovery

**Consider adding Cloudflare Tunnel** if you later need to expose the web dashboard publicly.

---

## Production Deployment Checklist

### Pre-deployment

- Choose identity provider (Google/GitHub/Microsoft)
- Create Tailscale account at [login.tailscale.com](https://login.tailscale.com)
- Generate auth keys (one-time for servers, or OAuth client secrets)
- Plan ACL policy (which device can reach which ports)

### Cloud server setup

- Assign public IP to VM (avoid NAT Gateway)
- Open UDP 41641 + 3478 in security group/firewall
- Install Tailscale with auth key (headless)
- Tag device: `--advertise-tags=tag:cloud-server`
- Disable key expiry for persistent servers
- Enable auto-updates: `tailscale set --auto-update`

### Local PC setup

- Install Tailscale (brew/App Store/download)
- Authenticate with same account
- Verify connection: `tailscale ping cloud-server`
- Check direct vs DERP: should see `via <ip>` not `via DERP`

### Post-deployment

- Replace default ACL with explicit rules + deny tests
- Set up webhooks for config change alerts
- Monitor with `tailscale status` / metrics endpoint
- Close unnecessary public ports on cloud firewall
- Document recovery procedure (auth key rotation, device re-auth)
- Enable log streaming to SIEM (if on paid plan)

---

## Implementation Recommendations

### For Device Farm specifically

```
┌────────────────────────────────────────────────────────────────────┐
│                         TAILNET                                    │
│                                                                    │
│  ┌─────────────────────┐              ┌─────────────────────────┐ │
│  │ Cloud Server         │  Tailscale   │ Local Mac               │ │
│  │ (public IP)          │◄───mesh────►│ (behind home router)    │ │
│  │                      │  100.64.x.x  │                         │ │
│  │  FastAPI :8080       │              │  ADB Transport          │ │
│  │  PostgreSQL :5432    │              │  Device Manager          │ │
│  │  Task Dispatcher     │              │                          │ │
│  │  Web Dashboard       │              │  USB Android devices    │ │
│  │  tag:cloud-server    │              │  tag:local-pc           │ │
│  └─────────────────────┘              └─────────────────────────┘ │
│                                                                    │
│  ACL: cloud↔local on ports 8080,5432,9008 only                    │
│  MagicDNS: cloud-server.tailnet.ts.net / local-mac.tailnet.ts.net │
└────────────────────────────────────────────────────────────────────┘
```

### Quick start (5 minutes)

```bash
# 1. Cloud server (Ubuntu)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --auth-key=tskey-auth-XXXXX --advertise-tags=tag:cloud-server

# 2. Local Mac
brew install --cask tailscale
# Open app → Sign in

# 3. Verify
tailscale ping cloud-server
# Should see: pong via <public-ip>:41641  (DIRECT)

# 4. Test service call
# From Mac:
curl http://cloud-server:8080/api/health
# From Cloud:
curl http://local-mac:8080/api/devices
```

### Docker Compose for cloud services

```yaml
# docker-compose.yml on cloud server
services:
  tailscale:
    image: tailscale/tailscale:latest
    hostname: device-farm-cloud
    env_file: .env  # TS_AUTHKEY=tskey-client-xxx?ephemeral=false
    environment:
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_EXTRA_ARGS=--advertise-tags=tag:cloud-server
    volumes:
      - ts-state:/var/lib/tailscale
    cap_add: [NET_ADMIN, SYS_MODULE]
    devices: [/dev/net/tun:/dev/net/tun]
    restart: unless-stopped

  api:
    image: device-farm-api:latest
    network_mode: service:tailscale
    depends_on: [tailscale]

  db:
    image: postgres:16
    network_mode: service:tailscale
    depends_on: [tailscale]
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  ts-state:
  pgdata:
```

### Common pitfalls to avoid

1. **Don't put cloud VM behind NAT Gateway** — use public IP for direct P2P
2. **Don't use reusable auth keys in production** — use OAuth client secrets
3. **Don't forget to mount `TS_STATE_DIR`** — container loses identity on restart
4. *Don't leave default `*:` ACL** — restrict to needed ports
5. **Don't skip `tailscale ping` verification** — confirm direct connection

---

## Resources & References

### Official Documentation

- [Tailscale Docs](https://tailscale.com/docs)
- [Production Best Practices](https://tailscale.com/docs/reference/best-practices/production)
- [Performance Best Practices](https://tailscale.com/docs/reference/best-practices/performance)
- [Deployment Checklist](https://tailscale.com/kb/1344/deployment-checklist)
- [AWS Reference Architecture](https://tailscale.com/docs/reference/reference-architectures/aws)
- [Docker Integration](https://tailscale.com/kb/1282/docker)
- [Firewall Ports](https://tailscale.com/kb/1082/firewall-ports)
- [ACL Management](https://tailscale.com/kb/1018/acls)
- [Tailnet Lock](https://tailscale.com/kb/1226/tailnet-lock/)
- [Tailnet Lock White Paper](https://tailscale.com/kb/1230/tailnet-lock-whitepaper/)
- [Security Hardening](https://tailscale.com/kb/1196/security-hardening/)
- [Connection Types](https://tailscale.com/kb/1257/connection-types)
- [DERP Servers](https://tailscale.com/kb/1232/derp-servers)

### Blog Posts & Deep Dives

- [Surpassing 10Gbps with Tailscale](https://tailscale.com/blog/more-throughput)
- [NAT Traversal Improvements Part 1](https://tailscale.com/blog/nat-traversal-improvements-pt-1)
- [NAT Traversal Part 2: Cloud Environments](https://tailscale.com/blog/nat-traversal-improvements-pt-2-cloud-environments)
- [How NAT Traversal Works](https://tailscale.com/blog/how-nat-traversal-works)
- [Introducing Tailnet Lock](https://tailscale.com/blog/tailnet-lock)
- [Docker + Tailscale Deep Dive](https://tailscale.com/blog/docker-tailscale-guide)
- [Peer Relays](https://tailscale.com/blog/peer-relays-international-networks)

### Community Resources

- [ScaleTail — Docker Sidecar Configs](https://github.com/tailscale-dev/ScaleTail)
- [hhftechnology/tailscale-sidecar](https://github.com/hhftechnology/tailscale-sidecar)
- [Adversis Hardening Guide](https://www.adversis.io/blogs/tailscale-hardening-guide)
- [Dev Server Setup (Tailscale + Caddy + Docker)](https://dev.to/shrsv/your-ultimate-dev-server-setup-with-tailscale-caddy-and-docker-1laf)
- [Tailscale Funnel vs Cloudflare Tunnel vs Nginx](https://onidel.com/blog/tailscale-cloudflare-nginx-vps-2025)
- [WireGuard vs Tailscale vs ZeroTier on VPS](https://onidel.com/blog/wireguard-vs-tailscale-vps-2025)

### Security

- [Tailscale Security Page](https://tailscale.com/security)
- [Security Bulletins](https://tailscale.com/security-bulletins)
- [Zero Trust Report 2025](https://tailscale.com/resources/report/zero-trust-report-2025)

---

## Unresolved Questions

1. **Peer Relay availability**: Oct 2025 feature — may still be in beta/limited rollout. Verify current status before relying on it.
2. **GCP Endpoint-Independent Mapping**: Exact configuration steps and port allocation limits need validation per specific GCP project.
3. **Tailscale + Android devices directly**: Could Tailscale run on managed Android devices to provide direct mesh, eliminating the local Mac as intermediary? Needs investigation.

