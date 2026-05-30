# DF-T-09-001 — Event ingest pipeline (domain → notification_service + activity_logger)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-001 |
| **Title** | Event ingest pipeline — domain phát event qua notification_service và activity_logger, tách write path khỏi domain |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:contract`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-09-03, FR-09-08, FR-09-09, FR-09-10, FR-09-12 |
| **Truy vết — UC refs** | UC-09-03, UC-09-06, UC-09-07, UC-09-10, UC-09-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Trước Epic này, domain module (Campaign, Scheduling, Devices, ...) có khả năng "tự ghi" vào bảng `notifications` hoặc `activity_log` nếu coder không cẩn thận. Hệ quả tiềm năng: format không nhất quán, miss event, khó audit, thêm channel mới phải sửa code domain.

Ticket này thiết lập **giao kèo nội bộ tách biệt write path khỏi domain** theo nguyên tắc đặc tả module mục 5.1 và 5.4: domain CHỈ phát event qua `notification_service` và `activity_logger`; hai service này độc quyền ghi vào bảng `notifications` và `activity_log`. Đồng thời, ticket này định nghĩa schema event chuẩn cho Campaign (dispatch / completed / failed / DLQ), Scheduling (run fail), Devices (offline / online), và bộ test guard CI từ chối insert/update SQL trực tiếp từ code domain.

Persona hưởng lợi: **Operator** (nhận event nhất quán), **Platform Engineer** (thêm channel mới không phải sửa domain), **Auditor** (activity_log đầy đủ và không sửa được).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** domain module chỉ phát event qua notification_service và activity_logger, không tự ghi DB
> **Để** notification format nhất quán, audit log không sửa được, và thêm channel mới (email, slack) chỉ cần sửa Module 09

## 4. Yêu cầu chức năng

- Hệ thống PHẢI expose service `notification_service.emit(event)` và `activity_logger.log(event)` — trace FR-09-12.
- Service `notification_service.emit()` PHẢI kiểm tra rule engine (DF-T-09-002), tạo notification record nếu thỏa, dispatch tới channel nếu có channel bật — trace FR-09-03.
- Service `activity_logger.log()` PHẢI luôn ghi activity_log entry (không phụ thuộc channel config) — trace FR-09-10.
- Hệ thống PHẢI định nghĩa schema event chuẩn cho 4 nhóm: Campaign (dispatch/completed/failed/DLQ), Scheduling (run_failed), Devices (offline/online), MCP (action_sensitive) — trace FR-09-08, FR-09-09.
- Hệ thống PHẢI có CI guard từ chối SQL insert/update trực tiếp tới `notifications` và `activity_log` từ code ngoài Module 09 — trace FR-09-12.
- Hệ thống PHẢI làm activity_log "append-style": không có endpoint update/delete từ API thông thường — trace FR-09-10.
- Hệ thống NÊN emit metric `domain_event_emitted_total` (counter theo event type + module).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Campaign module phát event qua service**

```
Given module Campaign cài đặt với contract event mới
And user dispatch campaign X
When campaign chạy xong với status=completed
Then Campaign module gọi `notification_service.emit({type: "campaign.completed", campaign_id: X, ...})`
And Campaign module gọi `activity_logger.log({...})`
And Campaign module KHÔNG có SQL insert tới `notifications` hay `activity_log`
And notification record tạo và activity_log entry append
```

**AC-2: Activity log append-style không sửa được**

```
Given activity_log có entry "campaign.completed at T"
When ai đó cố gọi UPDATE/DELETE qua API user thông thường
Then không có endpoint nghiệp vụ cho action này
And direct SQL từ code domain bị CI guard reject
And entry vẫn nguyên qua mọi life cycle thông thường
```

**AC-3: CI guard từ chối write trực tiếp**

```
Given developer thêm code trong module Campaign có dòng `INSERT INTO notifications ...`
When PR chạy CI
Then CI guard fail với message "Direct write to notifications/activity_log forbidden outside module notif-analytics. Use notification_service.emit() instead."
And PR bị block
```

**AC-4: Schema event chuẩn validate**

```
Given module Scheduling phát event `{type: "schedule.run_failed"}` thiếu field schedule_id
When `notification_service.emit()` nhận
Then service raise `EVENT_SCHEMA_INVALID` với chỉ rõ field thiếu
And event không được persist
And log error structured
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm rule engine cụ thể (event → channel) — sẽ ở DF-T-09-002.
- KHÔNG bao gồm channel implementation cụ thể (email, slack, webhook) — sẽ ở DF-T-09-003/004/005.
- KHÔNG bao gồm KPI rollup — sẽ ở DF-T-09-007.
- KHÔNG bao gồm retention policy — sẽ ở DF-T-09-012.
- KHÔNG bao gồm migration legacy code "tự ghi" trong domain (sẽ là sub-task riêng theo module).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `notification_service` với method `emit(event)`
- [ ] Implement `activity_logger` với method `log(event)`
- [ ] Implement schema validator cho event chuẩn (Campaign / Scheduling / Devices / MCP)
- [ ] Implement activity_log append-style (không expose update/delete endpoint)
- [ ] Refactor domain modules: thay direct write bằng service call

**Contract / API** (`layer:contract`)

- [ ] Định nghĩa schema event chuẩn (JSON schema + TypeScript types)
- [ ] Document mỗi event type với example payload

**Database / Migration** (`layer:db`)

- [ ] Bảng `notifications` (id, org_id, recipient_id, event_type, payload, status, created_at, read_at)
- [ ] Bảng `activity_log` (id, org_id, actor_id, event_type, resource_type, resource_id, payload, timestamp) — append only
- [ ] Index trên (org_id, recipient_id, status, created_at)
- [ ] Index trên (org_id, event_type, timestamp)
- [ ] Revoke UPDATE/DELETE permission trên 2 bảng cho mọi user/role ngoài service account của Module 09

**Documentation** (`layer:docs`)

- [ ] Tài liệu kỹ thuật `docs/modules/notif-analytics-service-contract.md`
- [ ] Tutorial "Phát domain event đúng cách" cho dev mới
- [ ] Cập nhật `docs/official_docs/modules/09-notifications-and-analytics.md` nếu có khác

**Test** (`layer:test`)

- [ ] Unit test notification_service và activity_logger
- [ ] CI guard test (grep + AST scan domain code)
- [ ] Integration test: Campaign chạy → event → notification + activity_log
- [ ] Schema validator test với event malformed

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-001-01 | Positive | Campaign module refactor xong | Dispatch campaign X, chạy tới completed | `notification_service.emit()` được gọi với event type `campaign.completed`; notification + activity_log tạo |
| TC-DF-T-09-001-02 | Positive | Scheduling module refactor xong | Schedule run fail | Event `schedule.run_failed` emit; activity_log entry append |
| TC-DF-T-09-001-03 | Negative | Developer thêm `INSERT INTO notifications` trong Campaign code | Push PR | CI guard fail; PR block với message rõ ràng |
| TC-DF-T-09-001-04 | Negative | Event payload thiếu field bắt buộc (vd campaign_id) | Gọi `emit()` | Raise `EVENT_SCHEMA_INVALID`; event không persist |
| TC-DF-T-09-001-05 | Edge | Service ngừng tạm thời (DB down 5s) | Domain emit 100 event | Event buffer ngắn hạn, persist sau khi DB recover; không mất event; log warning latency |
| TC-DF-T-09-001-06 | Edge | DB user role thường cố UPDATE activity_log row | Chạy SQL trực tiếp | Permission denied; entry bất biến |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** Không (ticket nền của Epic).

**Chặn:** DF-T-09-002, DF-T-09-007, DF-T-09-012, DF-T-09-013, và mọi ticket DF-E-09 khác.

**Phụ thuộc giữa Epic:**

- **DF-E-02 (Devices)** — refactor Devices module để dùng service.
- **DF-E-04 (Campaign)** — refactor Campaign module.
- **DF-E-05 (Scheduling)** — refactor Scheduling module.
- **DF-E-06 (Content)** — refactor Content module để emit event collection rollover.
- **DF-E-07 (Account)** — refactor Account module để emit event rotation.
- **DF-E-08 (Platform Ext)** — emit event extension load/unload.
- **DF-E-10 (MCP)** — emit event MCP action nhạy cảm.

**Rủi ro:**

- **Refactor breaking change cho domain module** → giảm thiểu: feature flag transition, parallel write (cũ + mới) trong 1 sprint trước khi remove path cũ.
- **CI guard false positive (false alarm)** → giảm thiểu: whitelist module 09 chính, test guard chạy trên repo trước merge.
- **Buffer event mất khi service down lâu** → giảm thiểu: persistent buffer (Redis/local file), monitor backlog.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả TC-DF-T-09-001-* map sang test tự động.
- [ ] Tài liệu service contract đã commit.
- [ ] CI guard test active.
- [ ] Migration tạo 2 bảng + index + permission revoke đã chạy trên staging.
- [ ] Telemetry: metric `domain_event_emitted_total`, log structured.
- [ ] Code review ≥ 1 approve từ owner DF-MOD-09.
- [ ] Đối soát: mọi domain module đã refactor (Campaign, Scheduling, Devices, Account, Content) — không còn direct write.
- [ ] Release notes ghi rõ breaking change cho dev integrating Device Farm.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — mục 5.1 (sơ đồ luồng), 6 (FR-09-03, FR-09-08, FR-09-09, FR-09-10, FR-09-12).
- **Module Campaign:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md).
- **Module Scheduling:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Operator, Platform Engineer.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Domain event, Activity log, Notification.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
