# Tailscale: Kết nối Cloud Server ↔ Local PC

## Tailscale là gì?

Tailscale là **mesh VPN** dựa trên WireGuard. Mỗi device được cấp IP `100.x.y.z` cố định, kết nối peer-to-peer trực tiếp, không cần port forwarding, end-to-end encrypted.

---

## 1. Cài đặt

### Cloud Server (Ubuntu/Debian)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled

# Headless server (không có browser) — dùng auth key:
# Tạo key tại https://login.tailscale.com/admin/settings/keys
sudo tailscale up --auth-key=tskey-auth-XXXXX
```

### Local PC (macOS)

```bash
brew install --cask tailscale
# Mở app → Sign in cùng account với cloud server
```

### Local PC (Windows)

Tải từ [tailscale.com/download](https://tailscale.com/download) → Sign in cùng account.

---

## 2. Xác nhận kết nối

```bash
tailscale status                    # Xem tất cả devices trên tailnet
tailscale ip -4                     # Xem Tailscale IP của mình
tailscale ping my-cloud-server      # Ping device kia
```

Với **MagicDNS** (bật mặc định), dùng hostname trực tiếp:

```bash
curl http://my-cloud-server:8080    # Từ Mac gọi lên cloud
curl http://my-macbook:3000         # Từ cloud gọi về Mac
```

---

## 3. Gọi service giữa Cloud ↔ Local

### Kịch bản A: Local chạy service, Cloud gọi vào

```bash
# Local Mac — chạy dev server
uvicorn web.server:app --host 0.0.0.0 --port 8080

# Cloud server — gọi trực tiếp
curl http://my-macbook:8080/api/devices
```

### Kịch bản B: Cloud chạy DB, Local kết nối

```bash
# Từ Mac
psql -h my-cloud-server -p 5432 -U myuser -d mydb
mongosh "mongodb://my-cloud-server:27017/device_farm"
```

### Kịch bản C: Device Farm split location

- **Cloud**: Web UI + Task Dispatcher + Database
- **Local PC**: ADB connections tới Android devices vật lý
- Hai bên giao tiếp qua Tailscale IP như cùng LAN

```
┌─────────────────────┐         Tailscale          ┌─────────────────────┐
│   Cloud Server      │◄──────── mesh VPN ────────►│   Local PC (Mac)    │
│                     │      100.x.y.z network      │                     │
│  - FastAPI (8080)   │                             │  - ADB Transport    │
│  - PostgreSQL (5432)│                             │  - Minicap/Touch    │
│  - Task Queue       │                             │  - Device Manager   │
│  - Web Dashboard    │                             │  - Android Devices  │
└─────────────────────┘                             └─────────────────────┘
```

---

## 4. `tailscale serve` — HTTPS reverse proxy nội bộ

```bash
# Expose port 3000 cho tailnet với auto HTTPS
tailscale serve --bg 3000

# Các device khác truy cập:
# https://my-macbook.tailnet-name.ts.net

# Xem config hiện tại
tailscale serve status

# Tắt
tailscale serve --bg 3000 off
```

---

## 5. `tailscale funnel` — Expose ra internet

```bash
# Expose port 3000 cho toàn bộ internet
tailscale funnel --bg 3000

# URL public: https://my-macbook.tailnet-name.ts.net
```

| | Node-to-Node | `serve` | `funnel` |
|---|---|---|---|
| Ai truy cập được | Tailnet members | Tailnet (HTTPS) | Internet (public) |
| Port | Bất kỳ | Bất kỳ | 443, 8443, 10000 |
| TLS | WireGuard | Auto cert | Auto cert |
| Use case | Nội bộ | Web service nội bộ | Webhook, demo |

---

## 6. Subnet Routing — Truy cập VPC resources

Khi cần truy cập thiết bị/service **không cài Tailscale** (VD: RDS, Cloud SQL, máy in LAN):

```bash
# Trên máy đóng vai subnet router (cloud server):
echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
sudo tailscale set --advertise-routes=10.0.0.0/24

# Approve routes tại Admin Console:
# https://login.tailscale.com/admin/machines → Edit route settings

# Trên Linux client muốn dùng routes:
sudo tailscale set --accept-routes
# macOS/Windows tự accept
```

**VD thực tế — Truy cập AWS RDS từ Mac:**

```bash
# EC2 advertise VPC CIDR
sudo tailscale set --advertise-routes=10.0.0.0/16

# Từ Mac:
psql -h 10.0.1.50 -p 5432 -U admin -d production
```

---

## 7. Tailscale SSH

```bash
# Bật SSH trên cloud server:
sudo tailscale set --ssh

# Từ Mac — SSH không cần key:
tailscale ssh my-cloud-server
```

---

## 8. ACL — Kiểm soát truy cập

Mặc định: **allow all** (mọi device gọi mọi device, mọi port). Nên restrict cho production.

Vào **Admin Console > Access Controls**, sửa policy:

```json
{
  "groups": {
    "group:devs": ["user@gmail.com"]
  },
  "tagOwners": {
    "tag:server": ["group:devs"]
  },
  "acls": [
    {
      "action": "accept",
      "src": ["group:devs"],
      "dst": ["tag:server:22,80,443,3000-9000"]
    }
  ]
}
```

Tag device:

```bash
sudo tailscale up --advertise-tags=tag:server
```

---

## 9. Security Checklist

- [ ] Restrict ACLs (bỏ default `*:*`)
- [ ] Bật 2FA trên identity provider (Google/GitHub)
- [ ] Đóng public ports trên cloud firewall (22, 80, 443) — truy cập qua Tailscale only
- [ ] Dùng one-time auth keys, xóa reusable keys sau khi deploy
- [ ] Disable key expiry chỉ cho persistent servers
- [ ] Bật Tailnet Lock cho high-security (device mới cần được ký bởi device tin cậy)
- [ ] Giữ Tailscale client updated (`tailscale update`)

---

## 10. Free Tier

| Feature | Giới hạn |
|---|---|
| Users | 3–6 |
| Devices | 100 |
| Subnet routers | ✅ |
| MagicDNS | ✅ |
| ACLs | ✅ |
| SSH | ✅ |
| Serve & Funnel | ✅ |
| HTTPS certs | ✅ |
| SSO/SAML | ❌ (paid) |

**Đủ dùng cho 1 developer kết nối cloud ↔ local.**

---

## Quick Start

```bash
# 1. Đăng ký tại https://login.tailscale.com

# 2. Cloud server (Ubuntu):
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --auth-key=tskey-auth-XXXXX

# 3. Local Mac:
brew install --cask tailscale
# Mở app → Sign in cùng account

# 4. Verify:
tailscale status
tailscale ping my-cloud-server

# 5. Dùng ngay:
curl http://my-cloud-server:8080   # từ Mac
curl http://my-macbook:3000        # từ cloud

# 6. (Optional) Lock down ACLs
# 7. (Optional) Đóng public cloud firewall ports
```

---

## Lệnh hay dùng

| Lệnh | Mô tả |
|---|---|
| `tailscale up` | Kết nối tailnet |
| `tailscale down` | Ngắt kết nối |
| `tailscale status` | Xem tất cả devices |
| `tailscale ip -4` | Xem IP Tailscale |
| `tailscale ping <host>` | Ping device |
| `tailscale netcheck` | Kiểm tra NAT/latency |
| `tailscale ssh <host>` | SSH không cần key |
| `tailscale serve <port>` | HTTPS nội bộ |
| `tailscale funnel <port>` | Expose ra internet |
| `tailscale set --hostname=<name>` | Đổi hostname |
| `tailscale set --advertise-routes=<CIDR>` | Quảng bá subnet |
| `tailscale update` | Cập nhật |
