# DF-T-01-012 — Session lifecycle & WebSocket auth

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-012 |
| **Title** | Session lifecycle (list, revoke, idle timeout) và WebSocket auth qua JWT |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:contract`, `type:feature`, `risk:auth` |
| **Truy vết — FR refs** | FR-01-02, FR-01-11 |
| **Truy vết — UC refs** | UC-01-02, UC-01-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

DF-T-01-002 build access + refresh token; DF-T-01-001 build WebSocket entrypoint skeleton (chưa auth). Ticket này hoàn thiện 2 phần liên quan: (1) **session management** — user xem được mình đang login từ đâu (browser nào, IP nào, lần cuối hoạt động), revoke session cụ thể (vd "phát hiện login lạ"); (2) **WebSocket auth** — kết nối `/ws` phải xác thực qua JWT, gắn `CurrentUser` cho mỗi message inbound, đóng kết nối khi token revoke; (3) **idle timeout** — refresh không dùng quá N ngày tự revoke.

Pain point: hiện tại nếu user nghi tài khoản bị compromise, cách duy nhất là đổi password (kèm theo invalidate mọi token). Ticket cho phép user revoke session cụ thể từ trang `/me/sessions`. WebSocket auth quan trọng cho stream/event realtime mà các Epic sau (Notif, device stream) cần.

P1 vì có thể defer 1 sprint nếu cần, nhưng cần xong trước khi mở DF-E-02 device stream.

## 3. Câu chuyện người dùng

> **Là** người vận hành
> **Tôi muốn** xem các session đang active và revoke session đáng ngờ
> **Để** kiểm soát truy cập tài khoản khi có dấu hiệu bất thường

> **Là** dashboard frontend
> **Tôi muốn** kết nối WebSocket sau khi đã xác thực JWT, nhận event realtime
> **Để** hiển thị thay đổi device state, scenario progress mà không cần polling

## 4. Yêu cầu chức năng

- Hệ thống PHẢI bảng `sessions` lưu mỗi refresh token với fields: `id`, `user_id`, `refresh_token_hash`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`, `device_fingerprint` (UA + IP hash), `last_ip` — trace FR-01-02.
- Hệ thống PHẢI cập nhật `last_used_at` mỗi lần refresh.
- Hệ thống PHẢI endpoint `GET /api/me/sessions` trả list session active của CurrentUser.
- Hệ thống PHẢI endpoint `DELETE /api/me/sessions/{session_id}` revoke session.
- Hệ thống PHẢI endpoint `DELETE /api/me/sessions` revoke tất cả session ngoại trừ current (logout-all-other).
- Hệ thống PHẢI auto-revoke session khi `last_used_at` > `idle_timeout` (default 30 ngày).
- Hệ thống PHẢI WebSocket `/ws` accept connection với JWT trong:
  - Query param `?token=...` (fallback nếu browser không support custom header), HOẶC
  - Subprotocol header `Sec-WebSocket-Protocol: Bearer.<token>`, HOẶC
  - Cookie (nếu cùng origin).
- Hệ thống PHẢI verify JWT ngay tại handshake; reject với close code 4401 nếu thiếu/expired/invalid — trace FR-01-11.
- Hệ thống PHẢI gắn `CurrentUser` cho mỗi connection context.
- Hệ thống PHẢI heartbeat ping/pong WebSocket mỗi 30s; đóng kết nối nếu không pong trong 60s.
- Hệ thống PHẢI khi token revoke (session revoked), đóng kết nối WS đang active của user đó trong < 5s.
- Hệ thống PHẢI emit audit event `session.revoked`, `ws.connected`, `ws.disconnected`, `ws.auth.rejected`.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: User xem session list**

```
Given alice đã login từ 3 device khác nhau (laptop, mobile, tablet)
When alice gọi GET /api/me/sessions
Then response 200 với array 3 session
And mỗi item có session_id, created_at, last_used_at, last_ip, user_agent_summary, is_current (true cho session hiện tại)
And refresh_token_hash KHÔNG được trả về
```

**AC-2: User revoke session khác**

```
Given alice có 3 session; current là S1
When alice DELETE /api/me/sessions/{S2.id}
Then response 204
And S2 revoked_at được set; S2 không refresh được nữa
And S1 và S3 vẫn active
And nếu S2 đang có WebSocket connection, kết nối đó bị đóng trong < 5s với code 4401
And audit log "session.revoked" với actor=alice, target=S2
```

**AC-3: Logout all other**

```
Given alice có 5 session; current S1
When alice DELETE /api/me/sessions (no id)
Then S2..S5 revoked; S1 còn
And WebSocket của S2..S5 đóng
```

**AC-4: WebSocket handshake với JWT hợp lệ**

```
Given alice có access token T1 hợp lệ
When alice mở WebSocket /ws?token=T1
Then handshake thành công (HTTP 101)
And connection có CurrentUser=alice
And audit log "ws.connected"
```

**AC-5: WebSocket reject token sai**

```
Given không có JWT hoặc token expired
When client mở WebSocket /ws
Then server đóng connection với close code 4401
And audit log "ws.auth.rejected"
```

**AC-6: Idle timeout tự revoke**

```
Given session S last_used_at = 31 ngày trước (idle_timeout=30)
When background job daily chạy
Then S revoked_at được set
And audit log "session.idle_timeout"
```

**AC-7: Revoke session đóng WebSocket đang chạy**

```
Given alice có session S1 với WS đang stream event
When admin/alice revoke S1
Then trong < 5s, WebSocket đóng với close code 4401
And client nhận event "connection_lost", thử reconnect → handshake fail
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm device fingerprinting nâng cao (canvas, fonts) — chỉ UA + IP.
- KHÔNG bao gồm geo-IP lookup hiển thị "Login từ Hà Nội" — defer.
- KHÔNG bao gồm session notification ("Bạn vừa login từ device mới") — defer DF-E-09 (Notif).
- KHÔNG bao gồm WebSocket message routing và pub/sub broker — chỉ build handshake + heartbeat; message routing là ticket riêng trong DF-E-09.
- KHÔNG bao gồm scaling WebSocket multi-instance (sticky session, Redis pubsub) — defer; M1 single-instance OK.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/auth/session_service.py` — list, revoke, idle check.
- [ ] Migration mở rộng bảng `refresh_tokens` thành `sessions` (rename + add columns).
- [ ] Endpoint `GET /api/me/sessions`, `DELETE /api/me/sessions/{id}`, `DELETE /api/me/sessions`.
- [ ] WebSocket auth middleware tại `/ws` endpoint.
- [ ] WebSocket heartbeat ping/pong.
- [ ] Connection registry (in-memory map session_id → WS connection) để force-close khi revoke.
- [ ] Background job daily idle_timeout check.

**Frontend** (`layer:frontend`)

- [ ] Trang `/me/sessions` list với button revoke.
- [ ] WebSocket client với reconnect logic; gửi token đúng cách.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 3 endpoint session.
- [ ] WebSocket protocol doc: handshake, ping/pong, close codes.
- [ ] Close code catalog: 4401 (auth), 4403 (revoked), 4408 (idle timeout).

**Database / Migration** (`layer:db`)

- [ ] Migration extend `refresh_tokens` → `sessions` table với fields mới.
- [ ] Index (user_id, revoked_at), (last_used_at) cho idle scan.

**Infra / DevOps** (`layer:infra`)

- [ ] Helm value `auth.session.idle_timeout_days` (default 30).
- [ ] WebSocket route ingress config (sticky session nếu multi-replica — flag for future).

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "Session & WebSocket".
- [ ] WebSocket protocol spec.

**Test** (`layer:test`)

- [ ] Unit test session service.
- [ ] Integration test 7 AC bằng WebSocket client (pytest-asyncio + websockets).
- [ ] Test force-close WS khi revoke trong < 5s.
- [ ] Load test 1000 WS concurrent connection.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-012-01 | Positive | alice login 3 device | GET /api/me/sessions | 200, 3 session, is_current đúng 1 |
| TC-DF-T-01-012-02 | Positive | alice có S1 (current), S2 | DELETE /api/me/sessions/{S2.id} | 204, S2 revoked; S1 còn |
| TC-DF-T-01-012-03 | Positive | alice access token hợp lệ | Mở WS /ws?token=... | 101 handshake; CurrentUser=alice; audit ws.connected |
| TC-DF-T-01-012-04 | Negative | alice cố revoke session của bob | DELETE /api/me/sessions/{bob.S.id} | 404 NOT_FOUND (không lộ tồn tại) |
| TC-DF-T-01-012-05 | Negative | WS không kèm token | Mở /ws | Server đóng close code 4401, audit ws.auth.rejected |
| TC-DF-T-01-012-06 | Negative | Token expired | WS với token expired | 4401, audit |
| TC-DF-T-01-012-07 | Edge | Session S đang có WS active; admin revoke S | Quan sát WS | WS đóng trong < 5s với close code 4403 |
| TC-DF-T-01-012-08 | Edge | Session idle 31 ngày | Job daily chạy | Session revoke; audit session.idle_timeout |
| TC-DF-T-01-012-09 | Edge | 1000 WS concurrent connection | Load test | Tất cả handshake OK; ping/pong duy trì; server không OOM |
| TC-DF-T-01-012-10 | Edge | WS client không pong trong 60s | Bỏ pong | Server đóng connection close code 4408 |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-002 (refresh token table), DF-T-01-005 (audit).

**Chặn:** Cross-Epic: DF-E-09 Notif (cần WebSocket auth), DF-E-02 device stream (cần WS auth pattern).

**Phụ thuộc giữa Epic:** Cấp khung WS auth cho mọi Epic dùng realtime.

**Rủi ro:**

- **R1 — Force-close WS không kịp khi revoke (multi-instance).** Giảm thiểu: M1 single-instance; multi-instance defer (cần Redis pub/sub).
- **R2 — Idle timeout xóa session active.** Giảm thiểu: update last_used_at mỗi refresh; threshold 30 ngày generous.
- **R3 — WebSocket connection registry memory leak.** Giảm thiểu: weakref + cleanup on disconnect.

**Phụ thuộc bên ngoài:** `websockets` Python library, FastAPI WebSocket support.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85%.
- [ ] 10 test case automation.
- [ ] WebSocket protocol doc reviewed.
- [ ] Force-close test pass (< 5s).
- [ ] Telemetry: `auth.session.count_active` gauge, `ws.connection.count` gauge, `ws.auth.rejected.count`.
- [ ] Performance: 1000 WS concurrent không degrade HTTP latency.
- [ ] Security review.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — FR-01-02, FR-01-11.
- **Ma trận năng lực:** "WebSocket entrypoint cho stream và event" — Active.
- **Nhóm người dùng:** Mọi persona dashboard.
- **Thuật ngữ:** WebSocket, Session.
