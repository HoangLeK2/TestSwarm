# DF-T-09-002 — Notification rule engine (event → channel + recipient)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-002 |
| **Title** | Notification rule engine — quyết định event nào tạo notification, gửi channel nào, gửi cho ai |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `type:feature`, `persona:platform-engineer`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-09-03, FR-09-08, FR-09-09, FR-09-14 |
| **Truy vết — UC refs** | UC-09-03, UC-09-06, UC-09-07, UC-09-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Sau khi event ingest pipeline (DF-T-09-001) hoạt động, mọi domain event đi qua `notification_service`. Câu hỏi tiếp: **mỗi event tạo notification cho ai, qua channel nào**. Mặc định "tạo notification cho mọi thành viên org" sẽ gây ngợp; mặc định "chỉ tạo cho người dispatch" lại thiếu cho event hệ thống (device offline).

Ticket này hiện thực hóa **rule engine** ánh xạ event → notification. Rule là declarative (config), không code: ví dụ `campaign.completed` → notify người dispatch (notification cá nhân); `device.offline` → notify mọi member có role `fleet-operator` (notification chung); `schedule.run_failed` → notify owner schedule. Rule có thể cấu hình per org. Rule engine cũng phân biệt **notification cá nhân vs notification chung** (FR-09-14).

Persona hưởng lợi: **Operator** (chỉ nhận event quan tâm), **Fleet Operator** (nhận event device-related), **Admin** (cấu hình rule cho org).

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức
> **Tôi muốn** cấu hình rule "event X → notify ai qua channel nào" theo declarative config
> **Để** mỗi persona chỉ nhận event quan tâm, không ngợp, và không phải sửa code khi thay đổi policy

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có rule engine declarative: rule = (event_type, recipient_resolver, channel_list) — trace FR-09-08, FR-09-09.
- Hệ thống PHẢI có recipient_resolver chuẩn: `dispatcher` (người dispatch resource), `owner` (chủ resource), `role:<role_name>` (mọi user có role), `all_org_members` — trace FR-09-14.
- Hệ thống PHẢI có default rule set ship cùng release (ví dụ Campaign.completed → dispatcher; device.offline → role:fleet-operator).
- Hệ thống PHẢI cho phép Admin override rule per org qua API.
- Hệ thống PHẢI phân biệt notification cá nhân (recipient_id != NULL) và notification chung (recipient_id = NULL, hiển thị cho mọi member) — trace FR-09-14.
- Hệ thống PHẢI evaluate rule sync khi `notification_service.emit()` được gọi.
- Hệ thống PHẢI có fallback: event không match rule nào → vẫn ghi activity_log nhưng không tạo notification.
- Hệ thống NÊN expose endpoint admin để xem rule hiệu lực và rule history.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Default rule Campaign.completed → notify dispatcher**

```
Given default rule set ship cùng release
And user X dispatch campaign C
When campaign C chạy completed
Then notification record tạo với recipient_id = X
And user X thấy notification cá nhân trong panel
And user Y khác trong org KHÔNG thấy notification này
```

**AC-2: Default rule device.offline → notify fleet-operator role**

```
Given user A, B có role `fleet-operator`, user C không có
And device D offline phát event
When notification_service emit event
Then notification chung tạo với recipient_id = NULL, target role = fleet-operator
And user A, B thấy trong panel
And user C KHÔNG thấy
And activity_log entry append (mọi event đều có entry)
```

**AC-3: Admin override rule per org**

```
Given org "acme" muốn không nhận notification campaign.completed (chỉ xem qua dashboard)
When admin POST /api/notif/rules với rule {event: "campaign.completed", recipient_resolver: "none"}
Then rule lưu vào DB cho org acme
And các campaign sau của acme KHÔNG tạo notification record nữa
And activity_log vẫn ghi đầy đủ
```

**AC-4: Event không match rule fallback**

```
Given có event type `experimental.new_event` chưa có rule
When notification_service emit
Then không có notification record tạo
And activity_log entry vẫn append
And log info "no rule matched for event type experimental.new_event"
And không lỗi
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm channel implementation (email, slack, webhook) — DF-T-09-003/004/005.
- KHÔNG bao gồm per-persona opt-in/out preference — DF-T-09-011.
- KHÔNG bao gồm alerting rule (threshold-based) — DF-T-09-009.
- KHÔNG bao gồm UI quản lý rule trong frontend — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `RuleEngine` với evaluate sync
- [ ] Implement recipient_resolver chuẩn (dispatcher, owner, role:*, all_org_members, none)
- [ ] Implement default rule set seed
- [ ] Implement rule override per org
- [ ] Hook vào `notification_service.emit()`

**Contract / API** (`layer:contract`)

- [ ] GET /api/notif/rules (xem rule hiệu lực)
- [ ] POST /api/notif/rules (override)
- [ ] DELETE /api/notif/rules/{rule_id}
- [ ] OpenAPI spec
- [ ] Authentication: role `org-admin`

**Database / Migration** (`layer:db`)

- [ ] Bảng `notification_rules` (id, org_id, event_type, recipient_resolver, channel_list_json, priority, created_at)
- [ ] Index trên (org_id, event_type)
- [ ] Seed default rules

**Documentation** (`layer:docs`)

- [ ] Tài liệu mô tả default rule set
- [ ] Tutorial "Cấu hình rule per org"

**Test** (`layer:test`)

- [ ] Unit test recipient_resolver
- [ ] Integration test: emit event → đúng recipient + đúng notification record
- [ ] Test override rule per org
- [ ] Test event không match → fallback activity_log

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-002-01 | Positive | Default rule + user X dispatch campaign | Campaign completed event emit | Notification cá nhân tạo cho X; activity_log entry append |
| TC-DF-T-09-002-02 | Positive | Default rule + 2 user role fleet-operator | Device offline event emit | Notification chung; 2 user fleet-operator thấy; user khác không thấy |
| TC-DF-T-09-002-03 | Positive | Admin override rule cho org acme: campaign.completed = none | Campaign of acme completed | Không notification tạo; activity_log vẫn append |
| TC-DF-T-09-002-04 | Negative | User không phải org-admin | POST /api/notif/rules | 403 Forbidden; rule không lưu |
| TC-DF-T-09-002-05 | Negative | Rule payload sai schema (recipient_resolver = "unknown") | POST | 400 với `RULE_INVALID_RESOLVER`; chỉ rõ value chấp nhận |
| TC-DF-T-09-002-06 | Edge | Event không match bất kỳ rule nào | Emit event | Không notification; activity_log vẫn append; log info |
| TC-DF-T-09-002-07 | Edge | 2 rule conflict cùng event_type cùng org | Emit | Engine chọn rule có priority cao hơn; log warning rule conflict |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-001.

**Chặn:** DF-T-09-003, DF-T-09-004, DF-T-09-005, DF-T-09-011.

**Phụ thuộc giữa Epic:**

- **DF-E-01 (Platform & Auth)** — role lookup `role:<role_name>` resolver phụ thuộc RBAC.

**Rủi ro:**

- **Rule eval sync làm chậm `emit()`** → giảm thiểu: cache compiled rules, latency budget < 50ms per emit.
- **Default rule sai cho 1 org** → giảm thiểu: admin override + audit log thay đổi rule.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả TC-DF-T-09-002-* map sang test tự động.
- [ ] Tài liệu default rule set đã commit.
- [ ] OpenAPI 3 endpoint mới đã commit.
- [ ] Migration seed default rule chạy trên staging.
- [ ] Telemetry: metric `rule_engine_eval_latency`, `notification_created_total` (by event_type).
- [ ] Code review ≥ 1 approve.
- [ ] Release notes liệt kê default rule set.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — mục 5.1, 6 (FR-09-03, FR-09-08, FR-09-09, FR-09-14).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Admin, Fleet Operator, Operator.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Notification, Domain event.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
