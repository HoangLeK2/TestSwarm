# DF-T-09-006 — Notification template i18n (vi/en) cho mọi event type

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-006 |
| **Title** | Notification template i18n — vi/en, deep link, alert templating chuẩn cho mọi event type |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:docs`, `type:feature`, `persona:social-data-operator`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-09-03, FR-09-15 |
| **Truy vết — UC refs** | UC-09-03, UC-09-06, UC-09-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Trước Epic này, mỗi channel (in-app, email, Slack, webhook) render notification text theo format tự do — dev gắn template ad-hoc vào code, không có version, không có i18n. Operator Việt Nam đọc notification tiếng Anh khó hiểu; admin thay đổi nội dung phải sửa code và redeploy.

Ticket này đưa toàn bộ render notification về một **template engine tập trung** (vi/en) với placeholder chuẩn (resource id, deep link, timestamp). Mỗi event type (campaign.completed, schedule.run_failed, device.offline, account.rotated, mcp.action_sensitive, ...) có một template cho mỗi locale, version-controlled trong repo, render qua hàm chung.

Persona hưởng lợi: **Social Data Operator** và **Fleet Operator** (đọc notification tiếng Việt rõ ràng), **Admin** (tùy chỉnh tone nội bộ qua override config), **Platform Engineer** (thêm event type mới chỉ cần thêm 2 template).

Ticket bám FR-09-03 (notification in-app), FR-09-15 (deep link về resource gốc); là dependency của DF-T-09-003/004/005 (channel render dùng template engine này).

## 3. Câu chuyện người dùng

> **Là** Operator (Social Data / Fleet / AI Ops Supervisor)
> **Tôi muốn** notification hiển thị bằng ngôn ngữ tôi chọn (vi/en), kèm deep link mở thẳng tài nguyên
> **Để** xử lý event nhanh, không phải dịch text tay hoặc tự tìm tài nguyên trong dashboard

Persona phụ: **Admin** (config locale mặc định cho organization).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có template engine render notification text theo locale (vi, en) — trace FR-09-03.
- Mỗi event type PHẢI có 2 template (title + body) cho mỗi locale; thiếu locale fallback về `en` — trace FR-09-03.
- Template PHẢI support placeholder chuẩn: `{resource_type}`, `{resource_id}`, `{resource_name}`, `{actor}`, `{timestamp}`, `{deep_link}`, `{summary}` — trace FR-09-15.
- Hệ thống PHẢI sinh `deep_link` tuyệt đối tới resource (campaign, execution, schedule, device, account) dùng base URL của organization — trace FR-09-15.
- User PHẢI có thuộc tính `preferred_locale` (default `vi`); notification render theo locale của recipient.
- Hệ thống PHẢI version template (template_version) để rollback an toàn khi nội dung mới sai.
- Template PHẢI được lint ở CI: thiếu placeholder bắt buộc, dùng placeholder không tồn tại, missing locale → fail.
- Hệ thống NÊN cho phép organization override 1 phần template (vd thêm hậu tố tên team) qua config; không bắt buộc trong release đầu.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Render đúng locale của recipient**

```
Given user U có preferred_locale="vi"
And event campaign.completed cho U
When notification_service emit và render
Then in-app notification có title vi (vd "Campaign X đã hoàn thành")
And body vi với placeholder thay đầy đủ
And deep_link mở đúng /campaigns/X
```

**AC-2: Fallback khi thiếu locale**

```
Given event type mới `account.rotated` chỉ có template `en`
And user U có preferred_locale="vi"
When notification render
Then dùng template en
And log warning `LOCALE_FALLBACK_USED event=account.rotated locale=vi`
And notification vẫn deliver, không block
```

**AC-3: CI lint template**

```
Given developer thêm template mới có placeholder `{unknown_var}`
When push PR
Then CI lint fail với message rõ "Unknown placeholder {unknown_var} in template campaign.completed.vi"
And PR bị block
```

**AC-4: Deep link đúng tới resource đã xóa**

```
Given campaign X bị xóa
And user U click notification có deep_link tới X
When frontend mở deep_link
Then hiển thị message rõ ràng "Tài nguyên đã bị xóa" thay vì 404 trắng
And notification record vẫn còn (không tự xóa)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm channel implementation cụ thể — đã ở DF-T-09-003/004/005.
- KHÔNG bao gồm UI quản trị template — DF-E-11 frontend.
- KHÔNG bao gồm A/B test template — backlog tương lai.
- KHÔNG bao gồm thêm locale ngoài vi/en — chờ yêu cầu thực tế.
- KHÔNG bao gồm template cho channel email HTML rich (chỉ plain text version 1) — sẽ refine khi cần.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `template_engine.render(event_type, locale, context)` trả về `{title, body, deep_link}`
- [ ] Implement `deep_link_builder` (resource_type, resource_id, org → URL tuyệt đối)
- [ ] Implement fallback locale logic (vi → en)
- [ ] Tích hợp template engine vào notification_service / 3 channel handler
- [ ] User preference column `preferred_locale`

**Contract / API** (`layer:contract`)

- [ ] Định nghĩa schema template `{event_type, locale, title, body, version}`
- [ ] Document placeholder chuẩn

**Database / Migration** (`layer:db`)

- [ ] Thêm column `users.preferred_locale` (default 'vi')
- [ ] Backfill từ user metadata nếu có

**Documentation** (`layer:docs`)

- [ ] Tạo `docs/modules/notif-template-catalog.md` liệt kê template vi/en cho mọi event type
- [ ] Hướng dẫn dev thêm event type mới: 2 template, lint pass

**Test** (`layer:test`)

- [ ] Unit test render với mỗi event type x locale
- [ ] Test fallback khi thiếu locale
- [ ] Test deep_link builder cho 5 resource type
- [ ] CI lint test (placeholder unknown, thiếu locale)
- [ ] Test tài nguyên đã xóa → frontend message graceful

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-006-01 | Positive | User U locale vi; event campaign.completed | Trigger emit | Title + body vi, deep_link đúng /campaigns/{id} |
| TC-DF-T-09-006-02 | Positive | User U locale en; event device.offline | Trigger emit | Title + body en, deep_link đúng /devices/{id} |
| TC-DF-T-09-006-03 | Negative | Template có placeholder không tồn tại | Push PR | CI lint fail; PR block |
| TC-DF-T-09-006-04 | Negative | Event type mới thiếu cả vi và en template | Trigger emit | Raise `TEMPLATE_NOT_FOUND`; notification không tạo; log error structured |
| TC-DF-T-09-006-05 | Edge | Locale vi thiếu, có en | Trigger emit cho user locale vi | Render bằng en; log warning fallback; notification deliver |
| TC-DF-T-09-006-06 | Edge | Resource đã soft-delete | Click deep_link | Frontend message "Tài nguyên đã bị xóa"; không 404 trắng |
| TC-DF-T-09-006-07 | Edge | Tên resource chứa ký tự đặc biệt (emoji, dấu) | Render | Escape đúng theo channel (HTML, Slack mrkdwn, plain text) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-001 (event ingest pipeline + schema event chuẩn).

**Chặn:** Phục vụ DF-T-09-003 (email), DF-T-09-004 (Slack), DF-T-09-005 (webhook) — 3 channel render qua template engine này.

**Phụ thuộc giữa Epic:**

- **DF-E-01** — user `preferred_locale` lưu ở user profile model của DF-E-01.
- **DF-E-11 (Frontend)** — UI cho user chọn locale; UI quản trị template (giai đoạn sau).

**Rủi ro:**

- **Template wording nhạy cảm văn hóa** → giảm thiểu: review nội dung bởi đội Product trước merge; copy-deck riêng.
- **Placeholder thiếu trong production khi event payload thay đổi** → giảm thiểu: schema event versioned, lint cross-check.
- **Performance khi render hàng nghìn notification/giây** → giảm thiểu: cache template parse; benchmark.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Unit test coverage ≥ 80%.
- [ ] CI lint template chạy + fail khi template invalid.
- [ ] Catalog template vi/en cho 100% event type produce trong release đã commit.
- [ ] Tài liệu `docs/modules/notif-template-catalog.md` cập nhật.
- [ ] Telemetry: counter `notification_render_total{event_type, locale, fallback}`.
- [ ] Code review ≥ 1 approve owner module + 1 approve Product (nội dung).
- [ ] Changelog ghi nhận "Notification i18n vi/en v1".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md §6 FR-09-03, FR-09-15](../../official_docs/modules/09-notifications-and-analytics.md).
- **Nhóm người dùng:** Social Data Operator (§3.1), Fleet Operator (§3.3), Automation Builder (§3.2).
- **Thuật ngữ:** [Notification](../../official_docs/00-glossary.md), [Deep link](../../official_docs/00-glossary.md), [Domain event](../../official_docs/00-glossary.md).
- **Ticket liên quan:** DF-T-09-003, DF-T-09-004, DF-T-09-005.
