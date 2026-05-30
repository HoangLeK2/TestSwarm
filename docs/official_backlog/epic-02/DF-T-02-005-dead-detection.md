# DF-T-02-005 — Dead detection — chuyển RECONNECTING → DEAD

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-005 |
| **Title** | Dead detection — chuyển thiết bị từ RECONNECTING sang DEAD khi vượt ngưỡng |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:infra`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-02, FR-03-04 (cross-Epic), FR-03-06 (cross-Epic) |
| **Truy vết — UC refs** | UC-02-02, UC-03-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Module DF-MOD-03 mục 5.2 mô tả ngưỡng RECONNECTING → DEAD cấu hình được. Module DF-MOD-02 mục 6 KPI yêu cầu "Thời gian phục hồi thiết bị sau sự cố mạng < 10 phút" — nếu quá ngưỡng, thiết bị chuyển DEAD và cần can thiệp.

Agent (DF-E-03) đẩy event `device.reconnecting` khi mất tín hiệu, sau đó emit `device.online` khi phục hồi. Nếu agent không emit online trong cửa sổ cấu hình (default 10 phút, có thể override), control plane phải chủ động chuyển state sang DEAD — vì agent có thể đã chết, không có khả năng emit thêm. Đây là detection chủ động ở control plane, không thể chỉ dựa vào event push.

Ticket này build worker scan thiết bị state=RECONNECTING + entered_at > threshold, push transition DEAD vào FSM (DF-T-02-002), trigger event `device.dead` cho alert (DF-E-09). Đồng thời cung cấp endpoint admin "revive" để chuyển DEAD → CONNECTING khi nguyên nhân vật lý đã sửa.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** thiết bị mất kết nối quá lâu được đánh dấu DEAD tự động
> **Để** biết thiết bị cần can thiệp thủ công (cáp, sạc, router) thay vì chờ vô vọng

## 4. Yêu cầu chức năng

- Hệ thống PHẢI worker scan device_states WHERE state=RECONNECTING AND entered_at < now - threshold mỗi 60s.
- Hệ thống PHẢI threshold cấu hình per tenant (default 600s = 10 phút).
- Hệ thống PHẢI transition RECONNECTING → DEAD chỉ thực hiện qua FSM engine (DF-T-02-002), không direct UPDATE.
- Hệ thống PHẢI emit event `device.dead` với reason="reconnect_timeout", last_known_state, entered_reconnect_at.
- Hệ thống PHẢI endpoint `POST /api/devices/{db_id}/revive` admin-auth, chuyển DEAD → CONNECTING (cần phối hợp agent re-bootstrap).
- Hệ thống PHẢI audit log "device.dead" và "device.revived".
- Hệ thống PHẢI nếu device DEAD có session active (race), force-release session đó (delegate sang DF-T-02-011 hoặc inline) và emit `session.lost_device`.
- Hệ thống PHẢI metric `device.dead_count{reason}`, gauge `device.state_count{state}`.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Device RECONNECTING quá 10 phút → DEAD**

```
Given device "df-001" state=RECONNECTING, entered_at = now - 700s
When dead-detection worker chạy
Then state transitions RECONNECTING → DEAD
And event device.dead emit với reason=reconnect_timeout
And audit log entry tạo
And metric device.dead_count tăng 1
```

**AC-2: Device phục hồi trước ngưỡng**

```
Given device "df-001" RECONNECTING entered_at = now - 300s
When agent emit device.online qua heartbeat
Then state transitions RECONNECTING → ONLINE (qua DF-T-02-002)
And worker scan sau đó không chuyển DEAD (vì state đã ONLINE)
```

**AC-3: Tenant override threshold**

```
Given org "low-quality-network" có dead_threshold_sec=1800
And device thuộc org đó RECONNECTING 700s
When worker chạy
Then KHÔNG chuyển DEAD (chưa quá 1800)
```

**AC-4: Force-release session khi device DEAD đang BUSY**

```
Given device "df-001" có session S1 active đồng thời state=RECONNECTING
When worker chuyển DEAD
Then S1 force-released với reason="device_lost"
And event session.lost_device emit
And owner nhận notification
```

**AC-5: Revive khi can thiệp thủ công**

```
Given device "df-001" state=DEAD
And admin alice gọi POST /api/devices/df-001/revive
Then state DEAD → CONNECTING
And audit log "device.revived" với actor=alice
And agent nhận hint re-bootstrap (event sang DF-E-03)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm reconnect strategy của agent — DF-T-02-006 cấu hình + DF-T-03-006 thực thi.
- KHÔNG bao gồm alert/notification email — DF-E-09.
- KHÔNG bao gồm tự động re-bootstrap thiết bị — DF-T-03-002 trigger.
- KHÔNG bao gồm UI revive button — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/devices/dead_detector.py` worker.
- [ ] Endpoint `POST /api/devices/{db_id}/revive` (RBAC admin).
- [ ] Hook force-release session khi DEAD.

**Database / Migration** (`layer:db`)

- [ ] Index trên `device_states (state, updated_at)` để worker query nhanh.
- [ ] Cột `tenant_settings.dead_threshold_sec`.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI revive endpoint.
- [ ] Event schema `device.dead`, `device.revived`, `session.lost_device`.

**Infra / DevOps** (`layer:infra`)

- [ ] Deploy worker (share with DF-T-02-004 hoặc separate).
- [ ] Alert rule: device.dead_count rate > 10/giờ.

**Documentation** (`layer:docs`)

- [ ] Runbook "Thiết bị DEAD — checklist can thiệp vật lý".

**Test** (`layer:test`)

- [ ] Unit test worker logic.
- [ ] Integration test 5 AC.
- [ ] Test 100 device RECONNECTING đồng thời quá hạn — tất cả chuyển DEAD đúng.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-02-005-01 | Positive | RECONNECTING 700s | Worker run | → DEAD, event emit |
| TC-DF-T-02-005-02 | Positive | DEAD device | Admin revive | → CONNECTING, audit |
| TC-DF-T-02-005-03 | Positive | RECONNECTING + session active | Worker run | DEAD + force-release session |
| TC-DF-T-02-005-04 | Negative | ONLINE device | Worker scan | Skip (state ≠ RECONNECTING) |
| TC-DF-T-02-005-05 | Negative | RECONNECTING 300s (chưa quá) | Worker scan | Skip |
| TC-DF-T-02-005-06 | Negative | Non-admin gọi revive | POST revive | 403 FORBIDDEN |
| TC-DF-T-02-005-07 | Edge | Tenant threshold 1800 | RECONNECTING 700s | Skip |
| TC-DF-T-02-005-08 | Edge | 100 device đồng thời RECONNECTING quá hạn | Worker run | Tất cả chuyển DEAD < 10s |
| TC-DF-T-02-005-09 | Edge | Device phục hồi đúng thời điểm worker scan (race) | Concurrent | Chỉ 1 trong 2 transition thắng (RECONNECTING→ONLINE hoặc →DEAD); FSM rule reject sai |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-002 (FSM), DF-T-02-003 (release), DF-T-01-003 (RBAC admin).

**Chặn:** DF-E-09 alert "device dead", DF-E-04-5 dispatch lọc DEAD ra khỏi pool.

**Phụ thuộc giữa Epic:** Đợi DF-T-03-006 heartbeat feed RECONNECTING event chính xác.

**Rủi ro:**

- **R1 — False positive khi mạng phòng máy yếu.** Giảm thiểu: threshold cấu hình per tenant; alert nếu dead rate cao bất thường.
- **R2 — Worker miss device do timezone bug.** Giảm thiểu: dùng UTC ở mọi nơi, test với clock skew.

## 10. Điều kiện hoàn thành

- [ ] Worker stable 24h trong staging.
- [ ] 9 test case pass.
- [ ] Runbook "DEAD device" reviewed.
- [ ] Metric `device.dead_count` xuất hiện trong dashboard.
- [ ] Audit log đầy đủ.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** DF-MOD-02 FR-02-02 + DF-MOD-03 FR-03-04, FR-03-06.
- **Liên quan:** DF-T-02-002 (FSM), DF-T-03-006 (heartbeat), DF-E-09 alert.
