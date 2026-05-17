# Product Requirements Document: Android Device Farm

---

- **Product Name:** Android Device Farm
- **Version:** 1.0.0
- **Author:** Device Farm Team
- **Last Updated:** 2026-03-26
- **Status:** In Development

---

## 1. Executive Summary

### Product Overview

Android Device Farm la mot nen tang quan ly va dieu khien thiet bi Android tu xa, ho tro streaming man hinh thoi gian thuc, dieu khien cam ung, thuc thi kich ban tu dong hoa va quan ly fleet thiet bi. He thong duoc thiet ke de phuc vu testing, automation va quan ly thiet bi Android quy mo lon voi kien truc multi-tenant.

### Problem Statement

- Quan ly nhieu thiet bi Android dong thoi phuc tap va ton thoi gian
- Thieu he thong tap trung de dieu khien, theo doi va tu dong hoa cac thao tac tren thiet bi
- Can mot giai phap cho phep truy cap tu xa va streaming man hinh thiet bi voi do tre thap
- Khong co cong cu tich hop AI de tu dong tao kich ban tu dong hoa tu ngon ngu tu nhien

### Core Value Proposition

- Quan ly tap trung hang tram thiet bi Android qua giao dien web
- Streaming man hinh thoi gian thuc (JPEG/H.264) voi do tre thap
- Dieu khien cam ung tu xa (tap, swipe, input text)
- Tu dong hoa bang AI - tao scenario tu ngon ngu tu nhien
- Ho tro 2 che do ket noi: WebSocket Agent va ADB over TCP
- Task queue uu tien cho viec dispatch cong viec len thiet bi

---

## 2. Goals and Objectives

### Business Goals

- Cung cap nen tang device farm cho testing va automation Android
- Ho tro multi-tenant (nhieu to chuc) voi phan quyen RBAC
- Mo rong quy mo len 1000+ thiet bi dong thoi
- Tich hop AI de giam thoi gian tao kich ban tu dong hoa

### User Goals

- Dieu khien thiet bi Android tu xa qua trinh duyet web
- Chay automation scenario tren nhieu thiet bi cung luc
- Theo doi trang thai thiet bi thoi gian thuc
- Tao scenario tu dong hoa nhanh chong bang ngon ngu tu nhien

### Product Objectives (OKRs)

```
Objective 1: Cung cap he thong dieu khien thiet bi on dinh
├─ KR 1.1: Ho tro ket noi dong thoi 100+ thiet bi
├─ KR 1.2: Do tre streaming < 200ms (LAN)
└─ KR 1.3: Uptime 99.5%+

Objective 2: Tu dong hoa thong minh
├─ KR 2.1: Ho tro 18+ loai step tu dong hoa
├─ KR 2.2: AI scenario generation tu ngon ngu tu nhien
└─ KR 2.3: Campaign fleet dispatch tren nhieu thiet bi

Objective 3: Multi-tenant va bao mat
├─ KR 3.1: JWT authentication voi access/refresh token
├─ KR 3.2: Role-based access control (admin/operator)
└─ KR 3.3: Organization-based device isolation
```

---

## 3. Target Audience

### Persona 1: QA Engineer / Test Automation Engineer

- **Role:** Kiem thu va tu dong hoa test tren Android
- **Goals:** Chay test tren nhieu thiet bi, model khac nhau cung luc
- **Pain Points:** Phai cam ung thu cong tren tung thiet bi, khong the test song song
- **Tech Proficiency:** High

### Persona 2: DevOps / Lab Manager

- **Role:** Quan ly phong lab thiet bi Android
- **Goals:** Theo doi trang thai thiet bi, bao tri tu xa, phan phoi thiet bi cho team
- **Pain Points:** Thieu visibility ve trang thai thiet bi, khong co cong cu quan ly tap trung
- **Tech Proficiency:** High

### Persona 3: Mobile Developer

- **Role:** Phat trien ung dung Android
- **Goals:** Debug va test nhanh tren thiet bi that tu xa
- **Pain Points:** Khong co thiet bi ngay luc can, phai den phong lab
- **Tech Proficiency:** High

---

## 4. System Architecture

### High-Level Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────┐
│  Next.js SPA │────▶│           FastAPI Backend                │
│  (Frontend)  │ WS  │                                          │
└─────────────┘     │  ┌──────────┐  ┌───────────┐            │
                    │  │ API Layer│  │ WebSocket │            │
                    │  │ (REST)   │  │ Manager   │            │
                    │  └────┬─────┘  └─────┬─────┘            │
                    │       │              │                    │
                    │  ┌────▼──────────────▼─────┐            │
                    │  │     Device Manager       │            │
                    │  │  (Registry + State)      │            │
                    │  └────┬─────────────┬──────┘            │
                    │       │             │                    │
                    │  ┌────▼────┐  ┌─────▼──────┐           │
                    │  │ Task    │  │ Dispatcher  │           │
                    │  │ Queue   │  │ (Daemon)    │           │
                    │  └─────────┘  └─────────────┘           │
                    │                                          │
                    │  ┌──────────────────────────┐           │
                    │  │    Transport Layer        │           │
                    │  │  ADB │ Minitouch │ Scrcpy │           │
                    │  │  U2  │ STF       │ WS Tun │           │
                    │  └──────────────────────────┘           │
                    └──────────────────────────────────────────┘
                              │                    │
                    ┌─────────▼──┐        ┌───────▼────────┐
                    │ PostgreSQL │        │ Android Devices │
                    │ (Async)    │        │ (Agent/ADB)     │
                    └────────────┘        └────────────────┘
```

### Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 14+, React, TypeScript, Radix UI, Tailwind CSS |
| **Backend** | FastAPI (Python 3.11+), Uvicorn, async/await |
| **Database** | PostgreSQL (asyncpg + SQLAlchemy async) |
| **Auth** | JWT (HS256), bcrypt_sha256 password hashing |
| **Device Comm** | WebSocket, ADB over TCP, Minitouch, UIAutomator2, scrcpy |
| **AI** | OpenAI API, Google Gemini, MCP Server |
| **Build** | pnpm (frontend), pip/poetry (backend) |
| **CI/CD** | Jenkins, Docker |

---

## 5. Features and Requirements

### 5.1 Device Management

**Description:** Dang ky, ket noi va quan ly lifecycle cua thiet bi Android.

**Two Connection Modes:**

| Mode | Use Case | Requirements |
|------|----------|-------------|
| **Mode A: WebSocket Agent** | Cloud/remote deployment | Android Agent APK installed, internet access |
| **Mode B: ADB over TCP** | Local lab/LAN | Android 11+ Wireless Debugging OR `adb tcpip 5555` |

**Device States:**
```
DISCONNECTED → CONNECTING → READY → BUSY → ERROR → DEAD
```

**Functional Requirements:**

1. Dang ky thiet bi qua serial hoac QR code (device_key 64-char)
2. Ket noi ADB over TCP bang IP:port
3. Theo doi trang thai thiet bi thoi gian thuc (WebSocket broadcast)
4. Tu dong phat hien thiet bi qua mDNS (Android 11+ Wireless Debugging)
5. Watchdog health check moi 10s, danh dau DEAD sau 120s khong phan hoi
6. Luu tru metadata: brand, model, android_version, sdk, screen size, battery

**Device Registration Flows:**

| Scenario | Action |
|----------|--------|
| New device | Create + assign to user |
| Existing, unowned | Claim for current user |
| Existing, owned by user | Idempotent update |
| Existing, owned by other | 409 Conflict |

**Priority:** P0 (Must Have)

---

### 5.2 Screen Streaming

**Description:** Stream man hinh thiet bi Android thoi gian thuc den trinh duyet.

**Functional Requirements:**

1. MJPEG streaming endpoint (`/stream/{serial}`) voi configurable interval
2. Single screenshot endpoint (`/screenshot/{serial}`)
3. H.264 streaming qua WebSocket (binary protocol: 0x01 JPEG, 0x10/0x11 H.264)
4. Configurable bitrate (default 8Mbps) va max FPS
5. Low-bandwidth mode (1s interval thay vi 33ms)
6. Multi-client subscription (asyncio queue per client)

**Streaming Sources:**

| Mode | Source | Format |
|------|--------|--------|
| WebSocket Agent | MediaProjection | JPEG/H.264 via WS |
| ADB Transport | scrcpy-server | H.264 → JPEG decode |

**Priority:** P0 (Must Have)

---

### 5.3 Touch & Input Control

**Description:** Dieu khien cam ung va nhap lieu tu xa tren thiet bi.

**Supported Actions (18+ step types):**

| Action | API Endpoint | Transport |
|--------|-------------|-----------|
| Tap | `POST /api/tap/{serial}` | Minitouch / U2 |
| Swipe | `POST /api/swipe/{serial}` | Minitouch / U2 |
| Long Tap | `POST /api/devices/{serial}/long_tap` | Minitouch / U2 |
| Scroll | `POST /api/devices/{serial}/scroll` | Minitouch |
| Input Text | `POST /api/devices/{serial}/input_text` | U2 send_keys |
| Key Press | `POST /api/key/{serial}` | U2 / ADB shell |
| Open URL | `POST /api/open_url/{serial}` | ADB am start |
| Tap by Selector | `POST /api/tap_selector/{serial}` | U2 find + tap |
| Hit Test | `POST /api/devices/{serial}/hit_test` | U2 hierarchy parse |

**Touch Method Priority:**
1. **Minitouch** (fastest, native input events)
2. **UIAutomator2** (accessibility-based, more reliable for selectors)
3. **ADB shell input** (fallback)

**Selector Strategy:**
- Prefer `text` (if < 80 chars) → `resource-id` (if has `/`) → `content-desc` XPath → `resource-id`

**Priority:** P0 (Must Have)

---

### 5.4 UI Hierarchy Inspection

**Description:** Doc va phan tich cay UI hierarchy cua thiet bi.

**Functional Requirements:**

1. `GET /api/devices/{serial}/hierarchy` - Raw XML hierarchy
2. `GET /api/devices/{serial}/ui_elements` - Parsed elements voi selector suggestions
3. Hit test: click position → best selector match
4. Cache hierarchy 2s de giam tai
5. Retry logic (3 lan) khi hierarchy rong

**UI Element Schema:**
```json
{
  "text": "Login",
  "resource_id": "com.app:id/btn_login",
  "content_desc": "",
  "class_name": "android.widget.Button",
  "bounds": [100, 200, 300, 250],
  "clickable": true,
  "selector_by": "resource-id",
  "selector_value": "com.app:id/btn_login"
}
```

**Priority:** P1 (Should Have)

---

### 5.5 Task Queue & Dispatcher

**Description:** He thong hang doi uu tien va dispatch cong viec len thiet bi.

**Functional Requirements:**

1. Priority-based queue (lower number = higher urgency, UNIX nice convention)
2. Two heap types: `_heap_any` (any device) + `_heap_targeted` (per serial)
3. Dispatcher loop moi 0.5s, assign task cho READY devices
4. Task timeout (default 300s) + retry (default 2 retries)
5. Rate limiting: max 60 tasks/device/minute
6. Task states: PENDING → RUNNING → DONE | FAILED | REQUEUED | CANCELLED
7. TTL cleanup: 24h cho terminal tasks

**Task Model:**
```python
Task(
    fn: Callable[[DeviceClient], Any],
    priority: int = 5,
    target: Optional[str] = None,  # serial or None for any
    timeout: float = 300,
    max_retries: int = 2,
)
```

**Priority:** P0 (Must Have)

---

### 5.6 Campaign Management

**Description:** Tao va quan ly campaign tu dong hoa tren nhieu thiet bi.

**Campaign Lifecycle:**
```
draft → running → paused → completed
```

**Functional Requirements:**

1. CRUD campaign (name, description, scenario, device_ids)
2. Gan/go thiet bi vao campaign
3. Tao scenario voi name, instructions (ngon ngu tu nhien), steps (JSON array), order
4. Compile scenario: AI generate steps tu instructions
5. Run campaign: Enqueue tasks cho tat ca thiet bi trong campaign
6. Fleet dispatch: Chay scenario tren fleet voi filter (state, model, max_devices)

**Scenario Step Types (18+):**
```
launch_app, open_url, wait, tap_position, tap_ratio, swipe_ratio,
tap, tap_selector, wait_element, assert_element, input_selector,
long_tap_selector, scroll_to, input_text, key, scroll_down,
wait_stable, dismiss_popup
```

**Priority:** P0 (Must Have)

---

### 5.7 AI Scenario Generation

**Description:** Su dung LLM de tu dong tao scenario steps tu ngon ngu tu nhien.

**Functional Requirements:**

1. Input: instructions (text), UI hierarchy XML (optional), device context
2. Output: Array of scenario steps (JSON)
3. Primary: AI MCP Server (Node.js)
4. Fallback: Direct LLM call (OpenAI / Google Gemini)
5. Tu dong fetch UI hierarchy tu thiet bi neu khong cung cap

**API:**
```
POST /api/campaigns/{campaign_id}/compile-scenario
POST /api/campaigns/{campaign_id}/scenarios/{scenario_id}/compile
```

**Priority:** P1 (Should Have)

---

### 5.8 Authentication & Authorization

**Description:** He thong xac thuc va phan quyen nguoi dung.

**Auth Flow:**
```
Register → Login → Access Token (24h) + Refresh Token (7d)
```

**Functional Requirements:**

1. User registration: email, name, password, role; successful registration also creates a default organization and owner membership
2. JWT Bearer token authentication (HS256)
3. Access token: 24h TTL (configurable)
4. Refresh token: 7d TTL (configurable)
5. Password hashing: bcrypt_sha256
6. Roles: `admin` (full access) / `operator` (own resources only)
7. Device key auth: 64-char random key cho WebSocket agent (no JWT needed)

**Priority:** P0 (Must Have)

---

### 5.9 Organization / Multi-Tenant

**Description:** Ho tro nhieu to chuc voi phan quyen thanh vien.

**Functional Requirements:**

1. Tao organization (businessName, businessEmail, businessLogo); new users get one default organization automatically at registration
2. Thanh vien voi role: owner / member
3. List organizations cua user
4. Unique constraint (organization_id, user_id)

**Priority:** P2 (Could Have)

---

### 5.10 MCP Integration (Model Context Protocol)

**Description:** MCP server cho phep AI tools (Cursor, Claude) tuong tac voi device farm.

**MCP Tools:**

| Tool | Purpose |
|------|---------|
| `df_start_session` | Bat dau session voi thiet bi |
| `df_end_session` | Ket thuc session |
| `df_list_devices` | Liet ke thiet bi |
| `df_tap`, `df_swipe` | Dieu khien cam ung |
| `df_shell` | Chay shell command |
| `df_screenshot` | Chup man hinh |
| `df_hierarchy` | Lay UI hierarchy |
| `df_tap_selector` | Tap theo selector |
| `df_run_scenario` | Chay scenario |
| `df_enqueue_task`, `df_list_tasks` | Quan ly task |
| `df_list_campaigns`, `df_create_campaign` | Quan ly campaign |
| `df_compile_campaign_scenario` | Compile scenario bang AI |
| `df_run_campaign` | Chay campaign |

**Priority:** P1 (Should Have)

---

### 5.11 Web Dashboard (Frontend)

**Description:** Giao dien web SPA cho quan ly va dieu khien thiet bi.

**Technology:** Next.js 14+, React, TypeScript, Radix UI, Tailwind CSS

**Key Features:**
1. Real-time device list voi status indicators
2. Live video streaming per device
3. Touch control overlay (tap, swipe truc tiep tren stream)
4. Campaign builder va scenario editor
5. UI hierarchy viewer
6. User auth (login/register)
7. Organization management
8. Auto-generated API client tu OpenAPI spec (`swagger-typescript-api`)

**Priority:** P0 (Must Have)

---

## 6. Data Model

### Entity Relationship

```
User ──1:N──▶ Device
User ──1:N──▶ Campaign
User ──N:M──▶ Organization (via OrganizationMember)

Device ──1:N──▶ DeviceSession
Device ──N:M──▶ Campaign (via CampaignDevice)

Campaign ──1:N──▶ Scenario

User ──1:N──▶ McpSession
```

### Core Entities

**User**
| Field | Type | Constraints |
|-------|------|------------|
| id | UUID | PK |
| email | String | Unique, Indexed |
| name | String | |
| hashed_password | String | |
| api_key | String | Unique |
| role | Enum | admin / operator |
| is_active | Boolean | Default true |
| created_at | Timestamp | Auto |

**Device**
| Field | Type | Constraints |
|-------|------|------------|
| id | UUID | PK |
| serial | String | Unique, Indexed |
| name | String | Nullable |
| device_key | String(64) | Unique |
| user_id | UUID | FK → User, Nullable |
| brand | String | Nullable |
| model | String | Nullable |
| android_version | String | Nullable |
| sdk_version | String | Nullable |
| screen_width | Integer | Nullable |
| screen_height | Integer | Nullable |
| adb_ip | String | Nullable |
| adb_port | Integer | Nullable |
| last_seen | Timestamp | Nullable |
| created_at | Timestamp | Auto |

**Campaign**
| Field | Type | Constraints |
|-------|------|------------|
| id | UUID | PK |
| name | String | |
| description | Text | Nullable |
| scenario | JSON | Legacy field |
| status | Enum | draft / running / paused / completed |
| user_id | UUID | FK → User |
| created_at | Timestamp | Auto |
| updated_at | Timestamp | Auto |

**Scenario**
| Field | Type | Constraints |
|-------|------|------------|
| id | UUID | PK |
| campaign_id | UUID | FK → Campaign |
| name | String | |
| instructions | Text | Nullable |
| steps | JSON Array | |
| order | Integer | |
| created_at | Timestamp | Auto |
| updated_at | Timestamp | Auto |

**Organization**
| Field | Type | Constraints |
|-------|------|------------|
| id | UUID | PK |
| business_name | String | |
| business_email | String | |
| business_logo | String | Nullable |
| created_at | Timestamp | Auto |

**OrganizationMember**
| Field | Type | Constraints |
|-------|------|------------|
| id | UUID | PK |
| organization_id | UUID | FK → Organization |
| user_id | UUID | FK → User |
| role | Enum | owner / member |
| **Unique** | | (organization_id, user_id) |

---

## 7. API Specifications

### API Overview

**Total Endpoints:** 70+
**Base URL:** `http://localhost:8081`
**Auth:** JWT Bearer Token (except public endpoints)

### Endpoint Categories

| Category | Prefix | Auth | Count |
|----------|--------|------|-------|
| Auth | `/api/auth` | No (register/login) | 4 |
| Devices | `/api/devices` | CurrentUser | 11 |
| Campaigns | `/api/campaigns` | CurrentUser | 18 |
| Users | `/api/users` | AdminUser | 3 |
| Organizations | `/api/organizations` | CurrentUser | 2 |
| Device Control - Gestures | `/api/tap, swipe, key, ...` | No | 7 |
| Device Control - Sessions | `/api/sessions` | No | 5 |
| Device Control - UI | `/api/devices/{serial}/hierarchy, ...` | No | 4 |
| Device Control - Scrcpy | `/api/devices/{serial}/scrcpy` | No | 2 |
| Device Control - Scenarios | `/api/devices/{serial}/scenario` | No | 3 |
| Device Control - Tasks | `/api/tasks, task, agent` | No | 3 |
| Device Control - Fleet | `/api/campaigns/{id}/run, fleet` | No | 3 |
| Public | `/ping, /api/devices/live, ...` | No | 4 |
| Media | `/stream, /screenshot` | No | 2 |
| Dashboard | `/` | No | 1 |

### Key API Examples

**Register:**
```http
POST /api/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "name": "Test User",
  "password": "secret123",
  "role": "operator"
}
```

On success, the backend also creates a default organization for the user and adds the user as `owner`. The response remains the user payload; clients load organizations after login through `/api/organizations`.

**Login:**
```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secret123"
}

→ { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```

**Connect ADB Device:**
```http
POST /api/devices/connect-adb
Authorization: Bearer <token>
Content-Type: application/json

{
  "ip": "192.168.1.100",
  "port": 5555
}
```

**Run Scenario on Device:**
```http
POST /api/devices/{serial}/scenario/run
Content-Type: application/json

{
  "steps": [
    { "type": "launch_app", "package": "com.example.app" },
    { "type": "wait", "seconds": 2 },
    { "type": "tap_selector", "by": "text", "value": "Login" },
    { "type": "input_selector", "by": "resource-id", "value": "com.example:id/email", "text": "test@example.com" }
  ]
}
```

**Fleet Run:**
```http
POST /api/fleet/run
Content-Type: application/json

{
  "steps": [...],
  "filter_state": "READY",
  "filter_model": "Pixel 7",
  "max_devices": 10,
  "priority": 3,
  "timeout": 600
}
```

---

## 8. WebSocket Protocols

### Frontend WebSocket (`/ws`)

**Purpose:** Real-time device status va screen streaming cho browser.

**Binary Frame Protocol:**
| Byte 0 | Payload | Description |
|--------|---------|-------------|
| `0x01` | JPEG data | JPEG frame |
| `0x10` | H.264 config | H.264 SPS/PPS (codec init) |
| `0x11` | H.264 NAL | H.264 video frame |

**JSON Commands (client → server):**
```json
{"action": "subscribe", "serial": "ABC123"}
{"action": "tap", "serial": "ABC123", "x": 500, "y": 800}
{"action": "swipe", "serial": "ABC123", "x1": 500, "y1": 800, "x2": 500, "y2": 200}
{"action": "key", "serial": "ABC123", "key": "back"}
```

### Device Agent WebSocket (`/device-agent`)

**Purpose:** Ket noi tu Android Agent APK den server.

**Handshake:** `ws://server/device-agent?key=<device_key>&pair=<pair_id>`

**Messages (device → server):**
```json
{"type": "hello", "serial": "ABC123", "brand": "Google", "model": "Pixel 7", ...}
{"type": "status", "battery": 85, "rotation": 0, ...}
{"type": "frame_b64", "data": "<base64 JPEG>"}
{"type": "h264_frame", "data": "<base64 H.264 NAL>"}
{"type": "tunnel_data", "tunnel_id": 1, "data": "<base64>"}
```

---

## 9. Configuration

### config.yaml

```yaml
web:
  host: "0.0.0.0"
  port: 8081
  ws_ping_interval: 20
  ws_ping_timeout: 120

ports:
  base_port: 20000
  stride: 10

device:
  minitouch_bin: "/data/local/tmp/minitouch"
  stf_package: "jp.co.cyberagent.stf"
  scrcpy_jar: "/opt/homebrew/share/scrcpy/scrcpy-server"
  scrcpy_bitrate: 8000000

watchdog:
  interval: 10
  max_retries: 3
  frame_stale_threshold: 5

dispatcher:
  loop_interval: 0.5
  max_tasks_per_minute: 60

database:
  enabled: true
  host: "localhost"
  port: 5432
  name: "device_farm"
```

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `FARM_CONFIG` | Path to config.yaml | - |
| `FARM_RELOAD` | Enable uvicorn reload | false |
| `FARM_FRONTEND_DIST` | Override SPA dist dir | - |
| `SECRET_KEY` | JWT signing key | Required |
| `JWT_ALGORITHM` | JWT algorithm | HS256 |
| `ACCESS_EXPIRE_HOURS` | Access token TTL | 24 |
| `REFRESH_EXPIRE_DAYS` | Refresh token TTL | 7 |
| `DATABASE_URL` | PostgreSQL DSN | - |
| `DEVICE_FARM_URL` | Server URL for agents | - |
| `DEVICE_FARM_WS` | WebSocket URL for agents | - |
| `AI_MCP_URL` | AI/MCP server URL | - |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `GEMINI_API_KEY` | Google Gemini API key | - |
| `NGROK_ENABLED` | Enable ngrok tunnel | false |
| `NGROK_AUTHTOKEN` | Ngrok auth token | - |
| `LOW_BW_MODE` | Low bandwidth streaming | false |

---

## 10. Device Connection Flows

### Flow A: WebSocket Agent (Cloud)

```
1. User: POST /api/devices/register → device_key + QR code
2. Android Agent: Scan QR → extract device_key + server URL
3. Agent: Open WS → /device-agent?key=<device_key>
4. Server: Validate key → DeviceAgentSession
5. Agent: Send "hello" {serial, brand, model, ...}
6. Server: ensure_device(serial) → DeviceClient
7. Server: Setup tunnels (u2, minitouch, stfservice)
8. Device: → READY state, ready for tasks
```

### Flow B: ADB over TCP (Lab)

```
1. Device: Enable Wireless Debugging (Android 11+) OR adb tcpip 5555
2. User: POST /api/devices/connect-adb {ip, port}
3. Server: AdbTransport.connect(ip, port)
4. Server: Read serial via adb shell
5. Server: AdbDeviceBootstrap starts:
   a. Collect metadata (brand, model, sdk, screen)
   b. Push + start scrcpy-server (H.264 stream)
   c. Push + start minitouch binary
   d. Install + start UIAutomator2 server
   e. Start battery/rotation polling
6. Device: → READY state
```

### Flow C: mDNS Auto-Discovery

```
1. Server: Start zeroconf listener (_adb-tls-connect._tcp)
2. Android 11+ device: Advertise Wireless Debugging service
3. Server: on_device(host, port, name) callback
4. Server: Auto register_adb_device(host, port)
5. → Follow Flow B from step 3
```

---

## 11. Non-Functional Requirements

### Performance

| Metric | Target |
|--------|--------|
| Stream latency (LAN) | < 200ms |
| API response time | < 100ms (CRUD), < 500ms (device control) |
| Concurrent devices | 100+ per instance |
| WebSocket connections | 500+ concurrent |
| Task dispatch interval | 500ms |
| Frame rate | 30 FPS (normal), 1 FPS (low BW) |

### Security

| Aspect | Implementation |
|--------|---------------|
| Authentication | JWT Bearer (HS256) |
| Password hashing | bcrypt_sha256 |
| Token management | Access (24h) + Refresh (7d) |
| Device auth | 64-char random device_key |
| CORS | Configurable (default: allow all for dev) |
| Role-based access | admin / operator |

### Scalability

| Aspect | Design |
|--------|--------|
| Database | Async PostgreSQL (pool_size=10, max_overflow=20) |
| WebSocket | Per-client asyncio queues |
| Task queue | In-memory, per-serial heaps |
| Device registry | Thread-safe dictionary |
| Streaming | Binary protocol, H.264 for bandwidth |

### Reliability

| Aspect | Implementation |
|--------|---------------|
| Watchdog | 10s interval, 120s timeout → DEAD |
| U2 health | 5s keep-alive ping, auto-reconnect |
| Task retry | Max 2 retries, exponential backoff |
| Hierarchy cache | 2s TTL, 3 retries on empty |
| Session lock | In-memory state machine (idle/reserved/running) |

---

## 12. Project Structure

```
device-farm/
├── device_farm/                    # Python Backend
│   ├── main.py                     # Server entry point
│   ├── config.yaml                 # Runtime configuration
│   ├── core/                       # Config, env, security
│   │   ├── config.py               # YAML config dataclasses
│   │   ├── env.py                  # Environment variable getters
│   │   └── security.py             # JWT token utilities
│   ├── db/                         # Database layer
│   │   ├── database.py             # SQLAlchemy async engine
│   │   ├── models/                 # ORM models
│   │   │   ├── user.py             # User model
│   │   │   ├── device.py           # Device + DeviceSession
│   │   │   ├── campaign.py         # Campaign + Scenario + CampaignDevice
│   │   │   ├── organization.py     # Organization + OrganizationMember
│   │   │   └── mcp_session.py      # MCP session tracking
│   │   └── crud/                   # CRUD operations
│   │       ├── user.py
│   │       ├── device.py
│   │       ├── campaign.py
│   │       ├── organization.py
│   │       ├── session.py
│   │       └── mcp_session.py
│   ├── api/                        # REST API layer
│   │   ├── mount.py                # Router mounting
│   │   ├── deps.py                 # Dependency injection (DB, auth)
│   │   ├── schemas/                # Pydantic request/response models
│   │   ├── crud/router.py          # Authenticated CRUD router
│   │   └── routes/                 # Endpoint handlers
│   │       ├── auth.py             # Login, register, refresh
│   │       ├── devices.py          # Device CRUD + ADB connect
│   │       ├── campaigns.py        # Campaign CRUD + scenarios
│   │       ├── users.py            # User management (admin)
│   │       ├── organizations.py    # Organization management
│   │       ├── public.py           # Health check, live devices
│   │       ├── device_media.py     # MJPEG stream, screenshot
│   │       ├── dashboard_page.py   # SPA serving
│   │       └── device_control/     # WebSocket + device control
│   │           ├── connect.py      # ADB register endpoint
│   │           ├── sessions.py     # MCP session management
│   │           ├── gestures.py     # Tap, swipe, key, scroll
│   │           ├── device_ui.py    # Hierarchy, selectors
│   │           ├── scrcpy.py       # Scrcpy attach/detach
│   │           ├── scenarios.py    # Scenario preview/run
│   │           ├── tasks_queue.py  # Task enqueue/status
│   │           └── campaign_fleet.py # Campaign/fleet dispatch
│   ├── web/                        # FastAPI app + WebSocket
│   │   ├── server.py               # App factory, middleware
│   │   └── ws.py                   # WS managers (frontend + agent)
│   ├── runtime/                    # Device runtime
│   │   ├── core/                   # Core components
│   │   │   ├── device_manager.py   # Device registry
│   │   │   ├── device_client.py    # Per-device proxy (1200+ lines)
│   │   │   ├── task_queue.py       # Priority task queue
│   │   │   ├── dispatcher.py       # Task dispatcher daemon
│   │   │   └── watchdog.py         # Health monitoring
│   │   ├── transports/             # Device communication
│   │   │   ├── adb_transport.py    # ADB over TCP + mDNS
│   │   │   ├── adb_device_bootstrap.py  # ADB device setup
│   │   │   ├── minitouch.py        # Minitouch TCP sender
│   │   │   ├── minitouch_ws.py     # Minitouch WebSocket sender
│   │   │   ├── u2_jsonrpc.py       # UIAutomator2 JSON-RPC
│   │   │   ├── scrcpy_receiver.py  # H.264 → JPEG decoder
│   │   │   ├── stf_client.py       # STF service events
│   │   │   └── ws_tunnel.py        # TCP-over-WebSocket tunnels
│   │   └── ai/                     # AI integration
│   │       ├── ai_client.py        # AI scenario orchestrator
│   │       └── ai_scenario.py      # Direct LLM fallback
│   ├── services/                   # Business logic
│   │   ├── campaign_dispatch.py    # Campaign task enqueue
│   │   ├── fleet_dispatch.py       # Fleet-wide dispatch
│   │   └── pairing.py             # QR pairing store
│   ├── tasks/                      # Task executors
│   │   ├── scenario_task.py        # Scenario step executor
│   │   └── example_task.py         # Demo tasks
│   ├── common/                     # Shared utilities
│   │   ├── session_lock.py         # Device session state machine
│   │   └── scenario_schema.py      # Scenario JSON schema
│   ├── mcp/                        # MCP protocol server
│   │   └── server.py               # MCP tools for Cursor/Claude
│   └── scenarios/                  # Scenario templates
├── front-end/                      # Next.js Frontend
│   ├── app/                        # App Router pages
│   ├── src/features/device-farm/
│   │   ├── components/             # React UI components
│   │   ├── pages/                  # Page layouts
│   │   ├── services/               # Auto-generated API client
│   │   ├── hooks/                  # Custom React hooks
│   │   └── stores/                 # State management
│   ├── package.json
│   ├── next.config.ts
│   ├── Dockerfile
│   └── Jenkinsfile
├── agent-boot/                     # Android Agent bootstrapping
├── STFService.apk/                 # STF Android service (Gradle)
├── scripts/
│   └── run_device_farm_mcp.sh      # MCP server launcher
├── flow.md                         # Architecture documentation
├── pyproject.toml                  # Python project config
└── README.md
```

---

## 13. Deployment

### Local Development

```bash
# Backend
cd device_farm
pip install -e .
python -m main

# Frontend
cd front-end
pnpm install
pnpm dev
```

**Requirements:**
- Python 3.11+
- PostgreSQL (optional: `database.enabled: false`)
- Node.js 18+ / pnpm
- scrcpy-server JAR (for ADB mode)

### Docker

```bash
# Frontend
cd front-end
docker build -t device-farm-frontend .

# Backend
docker build -t device-farm-backend .

# Database
docker run -d --name postgres -p 5432:5432 postgres:16
```

### Cloud (WebSocket Agent Mode)

- Deploy backend on cloud VM/container
- No ADB binary needed on server
- Devices connect via WebSocket (QR scan)
- Optional: ngrok for internet exposure

---

## 14. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Device disconnect giua task | High | Medium | Retry logic (max 2), watchdog auto-detect |
| UI hierarchy rong/thieu | Medium | Medium | 3 retries, 2s cache, fallback selectors |
| Memory leak voi nhieu devices | Medium | High | TTL cleanup (24h), queue size limits |
| WebSocket connection drop | High | Low | Auto-reconnect, ping/pong (20s/120s) |
| AI scenario generation sai | Medium | Low | Human review truoc khi run, preview mode |
| Database connection pool exhaustion | Low | High | pool_size=10, max_overflow=20, async sessions |
| Minitouch binary incompatible | Low | Medium | Fallback to U2 touch method |

---

## 15. Open Questions and Assumptions

### Assumptions

1. Thiet bi Android co man hinh bat va unlock
2. Mang LAN on dinh cho ADB mode
3. Internet on dinh cho WebSocket Agent mode
4. PostgreSQL available cho database features
5. Minitouch binary compatible voi device ABI

### Out of Scope (v1.0)

1. iOS device support
2. Video recording va replay
3. Performance profiling (CPU, memory, network)
4. Automated test report generation
5. Integration voi CI/CD pipelines (Jenkins, GitHub Actions)
6. Device reservation scheduling (calendar-based)
7. Multi-region deployment

---

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-26 | 1.0 | Initial PRD from codebase analysis | Claude |
