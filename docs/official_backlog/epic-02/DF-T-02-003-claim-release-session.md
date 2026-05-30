# DF-T-02-003 — Claim/release device session API

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-003 |
| **Title** | Claim/release device session — concurrency-safe reservation |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator`, `risk:data-loss` |
| **Truy vết — FR refs** | FR-02-03, FR-02-04 |
| **Truy vết — UC refs** | UC-02-04, UC-02-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module nói rõ "cùng một thiết bị phục vụ nhiều phiên làm việc — có lúc người vận hành thủ công đang điều khiển, có lúc scenario tự động chạy, có lúc AI agent đang dùng. Nếu không có cơ chế reserve, hai phiên cùng can thiệp một thiết bị sẽ đánh nhau." Ticket này build cơ chế claim/release đảm bảo mỗi thời điểm thiết bị thuộc đúng một session, với concurrency-safe primitives.

Ticket xây bảng `device_sessions` (session_id, device_id, owner_type, owner_id, claimed_at, released_at, last_heartbeat, ctx JSONB), endpoint `POST /api/devices/{db_id}/claim` body `{owner_type, owner_id, ttl_sec?, ctx?}`, endpoint `POST /api/devices/{db_id}/release` body `{session_id}`. Quyết định concurrency dùng `SELECT ... FOR UPDATE` trong transaction PostgreSQL hoặc Redis lock với timeout; tránh dual-write race. Khi claim thành công, đẩy event sang FSM (DF-T-02-002) để chuyển state ONLINE → BUSY với session_id gắn.

P0 vì là chốt chặn nghiệp vụ giữa DF-E-02 và DF-E-04 (campaign claim device để chạy scenario), DF-E-05 (scheduler dispatch), và DF-E-10 MCP (Preview). Sai claim = race = device điên loạn (2 lệnh cùng đè), một bug đắt giá cho B2B.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** reserve một thiết bị cho phiên thao tác thủ công
> **Để** thao tác không bị scenario tự động hoặc người khác chen ngang

> **Là** Automation Builder (gián tiếp qua DF-E-04 scenario runner)
> **Tôi muốn** scenario claim thiết bị trước khi thực thi step
> **Để** đảm bảo độc quyền điều khiển trong suốt run

## 4. Yêu cầu chức năng

- Hệ thống PHẢI bảng `device_sessions` với UNIQUE (device_id) WHERE released_at IS NULL — đảm bảo tối đa 1 session active per device — trace FR-02-03.
- Hệ thống PHẢI endpoint `POST /api/devices/{db_id}/claim` nhận `{owner_type: "manual"|"scenario"|"mcp", owner_id, ttl_sec?, ctx?}`.
- Hệ thống PHẢI claim thành công khi device state = ONLINE; reject với 409 `DEVICE_BUSY` nếu state ≠ ONLINE.
- Hệ thống PHẢI atomically check state + create session (transaction); KHÔNG có race window.
- Hệ thống PHẢI emit event `session.claimed` sang FSM để chuyển state ONLINE → BUSY.
- Hệ thống PHẢI endpoint `POST /api/devices/{db_id}/release` nhận `{session_id}`, set released_at, emit `session.released`.
- Hệ thống PHẢI release chỉ owner gọi được hoặc admin (DF-T-02-011 force-release).
- Hệ thống PHẢI endpoint `POST /api/sessions/{session_id}/heartbeat` cho owner refresh `last_heartbeat`, chống auto-release.
- Hệ thống PHẢI ttl_sec mặc định 30 phút; max 8 giờ; auto-release khi `last_heartbeat + ttl < now` (DF-T-02-004).
- Hệ thống PHẢI endpoint `GET /api/devices/{db_id}/session` trả session active hiện tại (nếu có) hoặc 204.
- Hệ thống PHẢI audit log claim/release với actor và session_id.
- Hệ thống PHẢI cross-tenant safety — claim device thuộc org khác trả 404.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Claim thành công lần đầu**

```
Given device "df-001" state=ONLINE, không session active
And alice là member acme có permission "device.claim"
When alice gọi POST /api/devices/df-001/claim với body {owner_type:"manual", owner_id:"alice", ttl_sec:1800}
Then response 201 với {session_id, claimed_at, ttl_sec:1800, owner_type, owner_id}
And device_sessions có row mới released_at IS NULL
And device state → BUSY (qua FSM event session.claimed)
And audit log "session.claimed"
```

**AC-2: Claim lần hai cùng device bị reject**

```
Given device "df-001" đã BUSY do session S1 của bob
When alice gọi POST /api/devices/df-001/claim
Then response 409 với body {"code":"DEVICE_BUSY", "current_session_id":"S1", "owner":"bob"}
And không tạo session mới
And state vẫn BUSY
```

**AC-3: Release thành công và device về ONLINE**

```
Given session S1 của bob active trên device "df-001"
When bob gọi POST /api/devices/df-001/release với {session_id:"S1"}
Then response 200
And device_sessions S1 có released_at = now
And device state → ONLINE
And audit log "session.released"
And alice claim ngay sau đó thành công
```

**AC-4: Release với session_id khác bị reject**

```
Given session S1 của bob active
When alice gọi POST /api/devices/df-001/release với {session_id:"S1"}
Then response 403 FORBIDDEN với {"code":"NOT_SESSION_OWNER"}
And session vẫn active
```

**AC-5: Heartbeat ngăn auto-release**

```
Given session S1 active với ttl_sec=600, claimed_at=10 phút trước
When bob gọi POST /api/sessions/S1/heartbeat tại phút thứ 5
Then last_heartbeat cập nhật
And auto-release worker tại phút thứ 11 không release S1 (vì last_heartbeat + 600 > now)
```

**AC-6: Concurrent claim — chỉ một thắng**

```
Given device "df-001" state=ONLINE
When alice và bob đồng thời POST claim (race < 50 ms)
Then đúng 1 request response 201, request kia 409 DEVICE_BUSY
And DB chỉ có 1 row trong device_sessions
And FSM chỉ nhận 1 event session.claimed
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm auto-release worker — DF-T-02-004 (ticket này chỉ định nghĩa schema và ttl).
- KHÔNG bao gồm admin force-release — DF-T-02-011.
- KHÔNG bao gồm queue khi DEVICE_BUSY — đặc tả module mục 10 chốt: không queue ở M2.
- KHÔNG bao gồm shadow session (observer) — module open question, defer.
- KHÔNG bao gồm session ctx schema chi tiết — DF-T-02-012 (per-device context).
- KHÔNG bao gồm gesture/hierarchy thực thi — DF-E-03 runtime path.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/devices/sessions.py` — claim, release, heartbeat service.
- [ ] Endpoint claim, release, heartbeat, get session.
- [ ] Sử dụng `SELECT ... FOR UPDATE` trong transaction để check + insert atomic.
- [ ] Validation owner_type enum, ttl_sec range.

**Frontend** (`layer:frontend`)

- [ ] Defer DF-E-11 (UI claim/release).

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 4 endpoint.
- [ ] Mã lỗi: DEVICE_BUSY, DEVICE_NOT_AVAILABLE, NOT_SESSION_OWNER, SESSION_NOT_FOUND, TTL_OUT_OF_RANGE.

**Database / Migration** (`layer:db`)

- [ ] Migration `device_sessions` (session_id UUID PK, device_id FK, owner_type, owner_id, claimed_at, released_at, last_heartbeat, ttl_sec, ctx JSONB).
- [ ] Partial UNIQUE INDEX (device_id) WHERE released_at IS NULL.
- [ ] Index (owner_type, owner_id), (last_heartbeat) for auto-release scan.

**Infra / DevOps** (`layer:infra`)

- [ ] Không có hạng mục mới đáng kể.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/devices.md` mục "Session lifecycle".
- [ ] Runbook "Stuck session — manual force release flow".

**Test** (`layer:test`)

- [ ] Unit test claim/release service.
- [ ] Integration test 6 AC.
- [ ] Concurrency test: 100 thread cùng claim một device → 1 thành công, 99 fail 409.
- [ ] Cross-tenant test.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-02-003-01 | Positive | Device ONLINE | POST claim với owner_type=manual | 201, session_id mới, state→BUSY |
| TC-DF-T-02-003-02 | Positive | Session active của bob | POST release với session_id của bob | 200, state→ONLINE |
| TC-DF-T-02-003-03 | Positive | Session active, ttl=600 | Heartbeat ở phút 5 | last_heartbeat cập nhật, session vẫn active đến phút 11 |
| TC-DF-T-02-003-04 | Negative | Device BUSY (S1 bob) | Alice POST claim | 409 DEVICE_BUSY với current_session_id, owner |
| TC-DF-T-02-003-05 | Negative | Device DEAD | POST claim | 409 DEVICE_NOT_AVAILABLE với state=DEAD |
| TC-DF-T-02-003-06 | Negative | Session S1 bob active | Alice POST release với S1 | 403 NOT_SESSION_OWNER |
| TC-DF-T-02-003-07 | Negative | Device thuộc org beta | Alice (acme) claim | 404 NOT_FOUND |
| TC-DF-T-02-003-08 | Negative | ttl_sec=999999 (vượt max 8h) | POST claim | 400 TTL_OUT_OF_RANGE |
| TC-DF-T-02-003-09 | Edge | 100 thread cùng claim device ONLINE | Concurrent POST claim | 1 success, 99 fail 409; DB consistent |
| TC-DF-T-02-003-10 | Edge | Network drop giữa claim → no release | Sau ttl, auto-release worker chạy | Session released, state→ONLINE (test cross với DF-T-02-004) |
| TC-DF-T-02-003-11 | Edge | Claim device đang state CONNECTING | POST claim | 409 DEVICE_NOT_AVAILABLE (chỉ ONLINE mới claim được) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-001 (device record), DF-T-02-002 (FSM state read + emit event), DF-T-01-002 (JWT auth), DF-T-01-003 (RBAC permission device.claim), DF-T-01-005 (audit).

**Chặn:** DF-T-02-004 (auto-release), DF-T-02-011 (force-release), DF-T-02-013 (stats theo session owner), DF-E-04 (scenario claim), DF-E-05 (dispatch claim).

**Phụ thuộc giữa Epic:** DF-E-04 scenario runner gọi claim trước khi chạy step.

**Rủi ro:**

- **R1 — Race condition khi 2 process cùng claim.** Giảm thiểu: `SELECT ... FOR UPDATE` + partial UNIQUE constraint.
- **R2 — Session orphan khi owner crash không release.** Giảm thiểu: ttl + auto-release (DF-T-02-004) + heartbeat.
- **R3 — Lock contention khi 1000 device claim đồng thời.** Giảm thiểu: row-level lock per device, không global lock.
- **R4 — Claim từ DF-E-04 vs manual operator đánh nhau về ưu tiên.** Giảm thiểu: ưu tiên FCFS (first-come first-served), không preempt; admin force-release nếu cần (DF-T-02-011).

**Phụ thuộc bên ngoài:** PostgreSQL transactions.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 90% cho `sessions.py`.
- [ ] 11 test case automation, concurrency test pass 100 thread.
- [ ] OpenAPI spec đầy đủ cho 4 endpoint.
- [ ] Audit log đầy đủ.
- [ ] Cross-tenant test pass.
- [ ] Metric: `session.claim_count`, `session.claim_conflict_count`, `session.release_count`, `session.duration_seconds`.
- [ ] Runbook "Stuck session" reviewed.
- [ ] Stress test: 1000 device, 1 claim mỗi 100 ms — không có deadlock, p99 latency < 200 ms.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/02-devices-and-control-plane.md`](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-03, FR-02-04, mục 5.2 (luồng reserve).
- **Ma trận năng lực:** "Reserve và release device session" — Active.
- **Nhóm người dùng:** Social Data Operator (primary), Automation Builder (consumer).
- **Thuật ngữ:** Device session, Reservation.
- **Liên quan:** DF-T-02-004 (auto-release), DF-T-02-011 (force-release), DF-T-04-* (scenario runner).
