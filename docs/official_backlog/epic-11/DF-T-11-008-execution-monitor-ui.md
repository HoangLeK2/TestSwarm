# DF-T-11-008 — Execution monitor UI — live log + per-device tiến độ

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-008 |
| **Title** | Execution monitor UI — live log, per-device progress, DLQ entry |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:social-data-operator`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-11-09 |
| **Truy vết — UC refs** | UC-11-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi campaign dispatch (hành trình Social Data Operator giai đoạn 4-5), người vận hành cần xem live: device nào đang chạy step nào, device nào fail, screenshot lúc fail. Đây là trang execution monitor. Cũng là entry quan trọng cho Automation Builder debug scenario.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator (hoặc Automation Builder debug)
> **Tôi muốn** mở execution monitor của campaign đang chạy thấy per-device progress, current step, live log, screenshot lúc fail
> **Để** can thiệp sớm khi fail và không phải đợi đến sáng hôm sau.

## 4. Yêu cầu chức năng

- Trang `/dashboard/campaigns/{id}/monitor` PHẢI list execution per-device với current step, status, started_at — trace FR-11-09.
- Live log PHẢI stream qua WebSocket cho từng execution — trace FR-11-09.
- Click execution PHẢI mở detail kèm step history + screenshot/hierarchy artifact.
- DLQ entry PHẢI mở trực tiếp từ execution fail — trace FR-11-09.
- Filter status per-device (running/completed/failed/retrying).
- Auto-refresh aggregate khi không có WebSocket.
- Cảnh báo proactive khi failure rate vượt ngưỡng cấu hình (hook tới Notifications DF-E-09).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Live log stream**

```
Given campaign C1 chạy trên 10 device
When user mở monitor
Then per-device row hiển thị status + current step
And click 1 row → log stream realtime trong < 2 s
```

**AC-2: Failed execution + DLQ**

```
Given execution E1 fail tại step "tap_selector"
When user click row fail
Then thấy screenshot + hierarchy lúc fail
And nút "Open DLQ entry" hoạt động
```

**AC-3: Filter status**

```
Given 10 execution, 7 done, 2 failed, 1 running
When filter status=failed
Then chỉ 2 row
```

**AC-4: Cảnh báo failure rate**

```
Given threshold cấu hình 10%
When failure rate vượt 10% trong 1 phút
Then UI hiển thị warning banner
And event notification được trigger (DF-E-09)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm DLQ resolution UI (chỉ link) — backlog riêng.
- KHÔNG bao gồm retry bulk — backlog.
- KHÔNG bao gồm chỉnh sửa scenario từ monitor.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Trang monitor + WebSocket hook.
- [ ] Per-device row + status badge.
- [ ] Detail panel artifact preview.
- [ ] Filter + warning banner.

**Contract / API** (`layer:contract`)

- [ ] Tiêu thụ generated client + WebSocket endpoint live log.

**Documentation** (`layer:docs`)

- [ ] UX doc.

**Test** (`layer:test`)

- [ ] E2E monitor live + reconnect.
- [ ] Test filter.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-008-01 | Positive | C1 chạy 10 device | Mở monitor | Per-device list + log stream |
| TC-DF-T-11-008-02 | Positive | E1 fail | Click | Screenshot + DLQ link |
| TC-DF-T-11-008-03 | Positive | Filter failed | Apply | Chỉ failed row |
| TC-DF-T-11-008-04 | Negative | WebSocket drop | Quan sát | Reconnect + status rõ |
| TC-DF-T-11-008-05 | Edge | Campaign 200 device | Mở | Render < 3 s + virtualization |
| TC-DF-T-11-008-06 | Edge | Failure rate vượt threshold | Quan sát | Warning banner + notification trigger |
| TC-DF-T-11-008-07 | Negative | User không có quyền xem campaign execution | Mở monitor bằng URL trực tiếp | Bị chặn 403, không hiển thị log hoặc artifact |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-005.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** **DF-E-04**, **DF-E-06** (artifact), **DF-E-09** (notification trigger).

**Rủi ro:**

- **WebSocket overload với 200 device:** server side aggregate + per-row subscription on-demand.
- **Log quá nhiều gây UI lag:** virtual list + retention client-side.

**Phụ thuộc bên ngoài:** Backend WebSocket.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: latency log_open, counter ws_drop.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-09](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md), [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md).
- **Nhóm người dùng:** Social Data Operator, Automation Builder.
- **Thuật ngữ:** Execution, DLQ, Artifact.
