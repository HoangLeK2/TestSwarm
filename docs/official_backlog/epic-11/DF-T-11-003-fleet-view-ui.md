# DF-T-11-003 — Fleet view UI — danh sách device + relay agent status

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-003 |
| **Title** | Fleet view UI — `/dashboard/devices`, `/dashboard/device-farm`, `/dashboard/relay-agents` |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-11-05, FR-11-07 |
| **Truy vết — UC refs** | UC-11-03, UC-11-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Fleet Operator là persona phụ thuộc dashboard nhiều nhất (mục persona ↔ module). Họ cần trang devices liệt kê 100-1000 device kèm trạng thái online/offline + heartbeat + filter (group, status), và trang relay agent biết relay nào online/offline/dead. Đây là entry point đầu mỗi ngày làm việc của Fleet Operator (hành trình 4.3).

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** mở `/dashboard/devices` thấy danh sách device kèm status, và mở `/dashboard/relay-agents` thấy relay agent status
> **Để** đầu ngày phát hiện ngay device/relay đang fail mà không phải chạy ADB qua từng cổng.

## 4. Yêu cầu chức năng

- Trang `/dashboard/devices` PHẢI list device kèm: serial, display_name, status (online/offline/busy), last_heartbeat, group, current_session_id (nếu busy) — trace FR-11-05.
- Filter PHẢI hỗ trợ: status (online/offline/busy), group, search theo serial/display_name — trace FR-11-05.
- Trang PHẢI refresh không phải reload toàn trang (polling hoặc websocket) — trace FR-11-05.
- Click device PHẢI mở device detail (DF-T-11-004) — trace UC-11-03.
- Trang `/dashboard/relay-agents` PHẢI list relay với: id, status (online/offline/dead), last_heartbeat, số device đang quản lý — trace FR-11-07.
- Cảnh báo PHẢI hiển thị khi heartbeat trễ > threshold — trace FR-11-07.
- Trang PHẢI hỗ trợ phân trang khi fleet > 200 device.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List device hiển thị đúng**

```
Given org có 250 device, 230 online, 20 offline
When user mở /dashboard/devices
Then bảng hiển thị 50 entry/trang với status đúng
And refresh polling 10 s cập nhật last_heartbeat
```

**AC-2: Filter kết hợp**

```
Given fleet đủ status mix + 3 group
When user filter status=online + group=A
Then chỉ hiển thị device thoả cả hai + count tổng đúng
```

**AC-3: Relay agent status với cảnh báo heartbeat trễ**

```
Given relay R1 heartbeat cách đây 90 s (threshold 60 s)
When user mở /dashboard/relay-agents
Then R1 hiển thị badge cảnh báo "heartbeat late"
And tooltip nói rõ thời gian trễ
```

**AC-4: Click device mở detail**

```
Given user ở /dashboard/devices
When click row device A1
Then chuyển sang /dashboard/devices/A1 (DF-T-11-004)
And breadcrumb đúng
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm device detail + live view — DF-T-11-004.
- KHÔNG bao gồm thao tác pair device — DF-E-03 hoặc admin UI riêng.
- KHÔNG bao gồm bulk action trên device — backlog.
- KHÔNG bao gồm metric chi tiết (RAM, pin, nhiệt độ) — out of scope module 11.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `devices/` với UI + hook + service.
- [ ] Bảng device với pagination + filter + search.
- [ ] Polling 10 s.
- [ ] Feature folder `relay-agents/`.
- [ ] Badge cảnh báo heartbeat.

**Contract / API** (`layer:contract`)

- [ ] Tiêu thụ generated client cho device.list, relay-agent.list.
- [ ] Nếu route relay-agent chưa trong client → Next API proxy có comment lý do.

**Documentation** (`layer:docs`)

- [ ] Doc UX behavior.

**Test** (`layer:test`)

- [ ] Test rendering 1000 device không lag.
- [ ] E2E filter + click detail.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-003-01 | Positive | 250 device | Mở trang | List + paging đúng |
| TC-DF-T-11-003-02 | Positive | Filter status + group | Apply | Subset chính xác |
| TC-DF-T-11-003-03 | Negative | Backend trả 500 | Mở | Error UI + retry, không trang trắng |
| TC-DF-T-11-003-04 | Negative | Search ký tự đặc biệt SQL injection | Type | Sanitize, không lộ backend error |
| TC-DF-T-11-003-05 | Edge | Fleet 0 device | Mở | Empty state hợp lý |
| TC-DF-T-11-003-06 | Edge | Relay heartbeat trễ 90 s | Inspect | Badge + tooltip chính xác |
| TC-DF-T-11-003-07 | Positive | Click row device | Navigation | Đúng URL detail |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001, DF-T-11-002.

**Chặn:** DF-T-11-004.

**Phụ thuộc giữa Epic:**

- **DF-E-02** — device list endpoint.
- **DF-E-03** — relay agent status.

**Rủi ro:**

- **Polling 10 s × 1000 device tải lớn:** server cache list; hoặc WebSocket push delta sau (lộ trình).
- **Heartbeat threshold sai gây cảnh báo nhiễu:** threshold config được.

**Phụ thuộc bên ngoài:** Service device + relay DF-E-02/03.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: page LCP, polling latency.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-05, FR-11-07](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md), [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md).
- **Nhóm người dùng:** Fleet Operator.
- **Thuật ngữ:** Device, Relay agent.
