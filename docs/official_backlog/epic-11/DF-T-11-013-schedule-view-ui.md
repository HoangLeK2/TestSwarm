# DF-T-11-013 — Schedule view UI — cron, toggle, run-now, history

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-013 |
| **Title** | Schedule view UI — `/dashboard/schedules` cron + toggle + run-now + history |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:social-data-operator`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-11-12 |
| **Truy vết — UC refs** | UC-11-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Schedule cron là cách Social Data Operator chạy campaign định kỳ (UC-11-10). Trang này quản lý: tạo schedule với cron expression, toggle bật/tắt mà không xóa, run-now ad hoc, xem history execution.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator hoặc Automation Builder
> **Tôi muốn** quản lý schedule cron qua dashboard — tạo, toggle, run-now, xem history
> **Để** campaign chạy đúng giờ không phải canh thủ công.

## 4. Yêu cầu chức năng

- Trang PHẢI list schedule với: name, cron expression (human readable), campaign target, enabled state, next_run, last_run — trace FR-11-12.
- Action: Create, Edit cron, Toggle enable, Run-now, Open history.
- Validate cron client-side trước khi gọi backend — trace FR-11-12.
- Toggle KHÔNG xóa cấu hình — chỉ flip `enabled` — trace FR-11-12.
- History PHẢI mở chi tiết execution gắn schedule run — trace FR-11-12.
- Hỗ trợ timezone aware — user thấy theo local TZ + lưu UTC.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Create schedule với cron**

```
Given user mở Create dialog
When input cron "0 2 * * *" + campaign C1 + enable
Then schedule tạo + hiển thị next_run đúng giờ local
And cron đọc người được "Mỗi ngày lúc 02:00"
```

**AC-2: Validate cron client-side**

```
Given user input cron sai "0 25 * * *"
When focus out
Then UI báo "Invalid cron: hour 25 out of range"
And Save bị disabled
```

**AC-3: Toggle off**

```
Given schedule S1 đang enabled
When toggle off
Then enabled=false, cấu hình giữ nguyên
And next_run = null
```

**AC-4: Run-now**

```
Given schedule S1 disabled
When click Run-now
Then trigger ad hoc execution
And history hiển thị entry run_now=true
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm scheduler engine — DF-E-05.
- KHÔNG bao gồm complex calendar (vd "first Monday").
- KHÔNG bao gồm chain schedule.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `schedules/`.
- [ ] Cron parser human readable.
- [ ] Validate client.
- [ ] Toggle + run-now.
- [ ] History panel.

**Contract / API** (`layer:contract`)

- [ ] Generated client DF-E-05.

**Documentation** (`layer:docs`)

- [ ] UX + cron cheatsheet.

**Test** (`layer:test`)

- [ ] Test cron validate.
- [ ] E2E toggle + run-now.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-013-01 | Positive | Cron hợp lệ | Create | Schedule + next_run đúng |
| TC-DF-T-11-013-02 | Positive | Toggle off | Click | enabled=false, không xóa |
| TC-DF-T-11-013-03 | Positive | Run-now | Click | Ad hoc execution + history entry |
| TC-DF-T-11-013-04 | Negative | Cron sai | Input | Validate fail rõ |
| TC-DF-T-11-013-05 | Edge | Timezone đổi giữa create và display | Quan sát | Hiển thị đúng theo TZ mới |
| TC-DF-T-11-013-06 | Edge | Schedule mỗi phút (load test) | Quan sát | UI vẫn responsive |
| TC-DF-T-11-013-07 | Negative | User không có quyền edit schedule | Click edit | Reject |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001, DF-T-11-002.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** **DF-E-05** (scheduler), **DF-E-04** (campaign link).

**Rủi ro:**

- **Cron timezone confusion:** lưu UTC, hiển thị local + tooltip TZ.
- **Run-now spam:** rate limit phía backend.

**Phụ thuộc bên ngoài:** Scheduler DF-E-05.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: counter run_now, toggle.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-12](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md).
- **Nhóm người dùng:** Social Data Operator, Automation Builder.
- **Thuật ngữ:** Schedule, Cron.
