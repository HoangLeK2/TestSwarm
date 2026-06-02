# DF-T-05-001 — Schedule data model & CRUD + toggle

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-001 |
| **Title** | Schedule data model + CRUD + toggle on/off |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Scheduling |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | `Done` |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-05-01, FR-05-03, FR-05-04, FR-05-05 |
| **Truy vết — UC refs** | UC-05-01, UC-05-02, UC-05-03, UC-05-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đây là ticket nền tảng của DF-E-05. Đặc tả module FR-05-01 đến FR-05-05 mô tả các thao tác cơ bản trên schedule: tạo, sửa, xoá, toggle bật/tắt. Khi chưa có entity ổn định, các ticket workflow / throttle / fairness không có chỗ persist trigger config.

Schedule là **đơn vị tự động hoá theo thời gian** của Operator: thay vì ngồi canh giờ bấm Run, họ tạo schedule một lần. Toggle on/off cho phép "tạm dừng trong kỳ nghỉ" mà không phải nhập cron lại — giảm friction lớn.

P0 vì block tất cả ticket khác của DF-E-05. SP 5 vì pattern tương tự DF-T-04-001 nhưng có thêm cron validation hook (DF-T-05-002).

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** tạo, sửa, xoá schedule và toggle bật/tắt mà không phải nhập cron lại
> **Để** vận hành theo lịch lặp không phải túc trực dashboard, và tạm dừng linh hoạt

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp entity `Schedule` với trường: `id`, `organization_id`, `name`, `description`, `cron_expression`, `target_campaign_id`, `status` (`enabled` | `disabled` | `deleted`), `created_by`, `created_at`, `updated_at`, `last_triggered_at`, `next_trigger_at` (computed cache).
- Hệ thống PHẢI cung cấp CRUD endpoints: `POST /schedules`, `GET /schedules`, `GET /schedules/{id}`, `PATCH /schedules/{id}`, `DELETE /schedules/{id}` (soft delete).
- Hệ thống PHẢI cung cấp toggle: `POST /schedules/{id}/toggle` body `{ enabled: bool }` — trace FR-05-05.
- Hệ thống PHẢI ràng buộc ownership: schedule thuộc org, cross-org isolation.
- Hệ thống PHẢI từ chối tạo schedule tên trùng trong cùng org.
- Hệ thống PHẢI validate cron expression cơ bản ở backend (chi tiết parsing ở DF-T-05-002): cú pháp 5 trường UNIX cron, không cho phép `@reboot` hoặc ký tự đặc biệt nguy hiểm.
- Hệ thống PHẢI validate `target_campaign_id` tồn tại, thuộc cùng org, không ở status `archived`.
- Hệ thống PHẢI giữ lịch sử schedule_run khi xoá schedule (chỉ status chuyển `deleted`, không hard delete) — trace FR-05-04.
- Hệ thống PHẢI emit domain event `schedule.created`, `schedule.updated`, `schedule.toggled`, `schedule.deleted`.
- Hệ thống PHẢI cho phép PATCH cron expression hoặc target_campaign_id — patch không tạo schedule mới — trace FR-05-03.
- Hệ thống PHẢI cập nhật `next_trigger_at` cache khi cron hoặc status thay đổi.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo schedule — luồng thành công**

```
Given user OrgA có quyền schedule.create
And campaign C tồn tại trong OrgA status="draft"
When POST /schedules body { name: "Morning", cron: "0 8 * * *", target_campaign_id: C }
Then 201, schedule_id mới, status="enabled" (default on khi tạo), next_trigger_at được compute
And event schedule.created phát
```

**AC-2: Toggle off rồi on**

```
Given schedule S status="enabled"
When POST /schedules/S/toggle body { enabled: false }
Then status="disabled", event schedule.toggled phát {to: "disabled"}
And tick định kỳ KHÔNG chạy schedule S
When POST /schedules/S/toggle body { enabled: true }
Then status="enabled", next_trigger_at được tính lại theo cron, không reset lịch sử run cũ
```

**AC-3: Patch cron — không tạo schedule mới**

```
Given schedule S cron="0 8 * * *"
When PATCH /schedules/S body { cron_expression: "0 9 * * *" }
Then 200, cron mới lưu, lịch sử run trước vẫn truy được, next_trigger_at = tick kế tiếp theo cron mới
And event schedule.updated phát
```

**AC-4: Cron không hợp lệ — reject**

```
Given user POST schedule cron="this is not cron"
When validate
Then 400 "INVALID_CRON_EXPRESSION" với message rõ ràng
And schedule không lưu
```

**AC-5: Soft delete — giữ history**

```
Given schedule S đã có 50 schedule_run lịch sử
When DELETE /schedules/S
Then S.status="deleted", không trigger thêm tick
And schedule_run cũ vẫn truy được qua GET /schedule-runs?since=
And GET /schedules/S trả 200 với status="deleted" (audit), không list default
```

**AC-6: Cross-org isolation**

```
Given schedule S OrgA
When OrgB user GET /schedules/S
Then 404 (không leak)
```

**AC-7: Target campaign archived**

```
Given campaign C status="archived"
When POST schedule target=C
Then 400 "CAMPAIGN_ARCHIVED"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm cron workflow durable / Temporal — DF-T-05-002.
- KHÔNG bao gồm run-now — DF-T-05-003.
- KHÔNG bao gồm schedule history list (chỉ chuẩn bị schema) — DF-T-05-010.
- KHÔNG bao gồm conflict detection — DF-T-05-009.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `Schedule` entity + repository.
- [ ] Service layer CRUD + toggle + duplicate name + ownership.
- [ ] Cron syntax validator (basic; library `croniter` hoặc tương đương).
- [ ] `next_trigger_at` cache updater.
- [ ] Domain event publisher.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI 6 endpoint.
- [ ] Mã lỗi: `INVALID_CRON_EXPRESSION`, `SCHEDULE_NAME_DUPLICATE`, `SCHEDULE_NOT_FOUND`, `CAMPAIGN_ARCHIVED`, `CAMPAIGN_NOT_FOUND`.

**Database / Migration** (`layer:db`)

- [ ] Bảng `schedules` với unique index (organization_id, lower(name)) partial WHERE status != 'deleted'.
- [ ] Cột `cron_expression VARCHAR(128)`.
- [ ] Cột `next_trigger_at TIMESTAMP` index cho scheduler poll nhanh.

**Documentation** (`layer:docs`)

- [ ] Doc cron syntax được hỗ trợ + ví dụ.
- [ ] Doc lifecycle schedule.

**Test** (`layer:test`)

- [ ] Unit test CRUD + toggle.
- [ ] Test duplicate name + cross-org isolation.
- [ ] Test cron validate basic.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-05-001-01 | Positive | OrgA campaign C draft | POST schedule cron="0 8 * * *" target=C | 201, status="enabled", next_trigger_at set |
| TC-DF-T-05-001-02 | Positive | Schedule S enabled | Toggle off | Status="disabled", tick không chạy; toggle on khôi phục enabled |
| TC-DF-T-05-001-03 | Positive | Schedule S | PATCH cron | Cron update, next_trigger_at re-compute, history cũ giữ |
| TC-DF-T-05-001-04 | Negative | Cron sai cú pháp "blah" | POST | 400 "INVALID_CRON_EXPRESSION" |
| TC-DF-T-05-001-05 | Negative | Schedule tên "X" đã có OrgA | POST tên "x" | 409 "SCHEDULE_NAME_DUPLICATE" |
| TC-DF-T-05-001-06 | Edge | Schedule S có 50 history | DELETE S | Status="deleted", history truy được, không trigger thêm |
| TC-DF-T-05-001-07 | Negative | Campaign archived | POST target archived | 400 "CAMPAIGN_ARCHIVED" |
| TC-DF-T-05-001-08 | Negative | OrgB GET schedule OrgA | GET | 404 |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-E-01 (RBAC, org), DF-E-04 (DF-T-04-006 campaign entity).

**Chặn:** DF-T-05-002, DF-T-05-003, DF-T-05-009, DF-T-05-010, DF-T-05-011, mọi ticket khác DF-E-05.

**Phụ thuộc giữa Epic:** DF-E-04 phải có campaign entity sẵn.

**Rủi ro:**

- **Cron parser khác biệt frontend / backend:** đặc tả module mục 8 cảnh báo → ticket này dùng backend parser chuẩn, dùng cùng library cho FE (DF-E-11) — chốt library: `croniter` (Python) hoặc tương đương.
- **Soft delete dư thừa:** unique name có thể tái sử dụng nếu unique index partial; ổn.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Test case mapped.
- [ ] Doc cron syntax published.
- [ ] Telemetry: schedule.created/toggled/deleted metric.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — FR-05-01, 03, 04, 05.
- **Thuật ngữ:** Schedule, Cron expression, Toggle.
- **Nhóm người dùng:** Operator.
