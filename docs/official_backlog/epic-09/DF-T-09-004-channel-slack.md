# DF-T-09-004 — Channel: Slack (payload + deep link)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-004 |
| **Title** | Channel Slack — incoming webhook + payload chuẩn + deep link tới resource gốc |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `type:feature`, `persona:operator`, `persona:ai-ops` |
| **Truy vết — FR refs** | FR-09-01, FR-09-02, FR-09-07, FR-09-13, FR-09-15 |
| **Truy vết — UC refs** | UC-09-01, UC-09-02, UC-09-06, UC-09-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Slack là tích hợp ngoài đã ở **Active (preview)** trong đặc tả module mục 7. Hiện tại sản phẩm hỗ trợ Slack qua webhook generic (HTTP POST tới Incoming Webhook URL). Tuy nhiên payload chưa được format chuẩn cho Slack — Slack có Block Kit cho rich message; payload generic chỉ là JSON plain hiển thị xấu. Đồng thời, deep link tới resource (campaign URL, execution URL, device URL) chưa luôn đúng — FR-09-15 yêu cầu deep link mở thẳng tới tài nguyên gốc.

Ticket này hiện thực hóa **Slack channel chuyên dụng** với payload Block Kit, deep link đúng, ghi nhận delivery, error handling cho rate limit Slack (HTTP 429).

Persona hưởng lợi: **Operator** (Slack là channel chính của nhiều team), **AI Operations Supervisor** (MCP action nhạy cảm đẩy Slack để review nhanh).

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức (hoặc Supervisor)
> **Tôi muốn** cấu hình channel Slack với Incoming Webhook URL và nhận notification có format Block Kit và deep link
> **Để** team đọc nhanh trong Slack và click trực tiếp về Device Farm dashboard thay vì copy URL

## 4. Yêu cầu chức năng

- Admin PHẢI tạo channel kiểu Slack với config: webhook_url, channel name (cosmetic) — trace FR-09-01.
- Hệ thống PHẢI CRUD channel Slack — trace FR-09-02.
- Hệ thống PHẢI format payload Block Kit: header (event type), section (summary), button (deep link tới resource) — trace FR-09-07, FR-09-15.
- Mỗi notification gửi Slack PHẢI chứa deep link mở đúng resource trong Device Farm dashboard — trace FR-09-15.
- Hệ thống PHẢI handle Slack rate limit (HTTP 429): backoff theo `Retry-After` header.
- Hệ thống PHẢI ghi nhận delivery result (HTTP status, latency) — trace FR-09-13.
- Hệ thống PHẢI handle webhook URL invalid hoặc revoked (HTTP 404) — admin nhận warning.
- Hệ thống NÊN có thumbnail icon theo loại event (campaign vs schedule vs device) để dễ nhận diện trong Slack.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo channel Slack**

```
Given admin có role org-admin
And admin có Slack Incoming Webhook URL hợp lệ
When admin POST /api/notif/channels với type=slack, config={webhook_url, channel_name}
Then channel tạo thành công, enabled=true
And response 201
```

**AC-2: Gửi notification campaign.completed tới Slack**

```
Given channel Slack đang bật cho org acme
And rule campaign.completed → notify dispatcher via slack
And user X dispatch campaign C, campaign chạy completed
When notification trigger
Then Slack message render Block Kit với:
  - Header "Campaign Completed: <name>"
  - Section text với status, duration, item_count
  - Button "Open in Device Farm" trỏ tới /campaigns/{id}
And HTTP POST Slack webhook trả 2xx
And delivery log ghi success
```

**AC-3: Handle Slack rate limit**

```
Given Slack trả HTTP 429 với Retry-After: 30
When dispatcher gửi tiếp
Then backoff 30s
And retry sau đúng thời gian
And nếu lại 429, backoff theo header mới
And metric `slack_rate_limit_total` tăng
```

**AC-4: Webhook URL invalid trả admin warning**

```
Given channel Slack có webhook URL bị revoked (HTTP 404)
When event trigger
Then delivery fail với delivery_status=invalid_webhook
And admin nhận notification "Slack channel X has invalid webhook, please update"
And channel auto-disable sau 3 fail liên tiếp
```

**AC-5: Deep link đúng resource**

```
Given event campaign.completed với campaign_id=C123
When Slack message render
Then button URL là https://<app-domain>/campaigns/C123
And click button mở campaign detail page
And nếu campaign đã bị xóa, page hiển thị "Resource not found" rõ ràng (không 404 trắng)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm Slack OAuth (đăng nhập sản phẩm qua Slack) — không scope module này.
- KHÔNG bao gồm Slack slash command (chạy lệnh Device Farm từ Slack) — Lộ trình riêng.
- KHÔNG bao gồm Slack DM (chỉ channel webhook) — Slack DM cần OAuth.
- KHÔNG bao gồm digest Slack — DF-T-09-010.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `SlackDispatcher` extend webhook dispatcher base
- [ ] Implement Block Kit payload builder
- [ ] Implement rate limit handler (HTTP 429 + Retry-After)
- [ ] Implement deep link resolver từ event payload
- [ ] Auto-disable channel sau 3 fail liên tiếp

**Contract / API** (`layer:contract`)

- [ ] Schema config slack: webhook_url, channel_name
- [ ] OpenAPI cập nhật

**Documentation** (`layer:docs`)

- [ ] Tutorial "Cấu hình Slack channel"
- [ ] Document Block Kit format mỗi event type

**Test** (`layer:test`)

- [ ] Unit test SlackDispatcher
- [ ] Integration test với mock Slack endpoint
- [ ] Test rate limit handling
- [ ] Test deep link cho 5 event type chính

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-004-01 | Positive | Slack mock endpoint chạy local | Trigger campaign.completed | Block Kit payload đúng schema; button URL đúng; HTTP 2xx |
| TC-DF-T-09-004-02 | Positive | Channel slack cấu hình cho org | Trigger 5 event type khác nhau | 5 Slack message với format đúng từng loại, icon đúng |
| TC-DF-T-09-004-03 | Negative | Webhook URL revoked (Slack trả 404) | Trigger | delivery_status=invalid_webhook; admin nhận warning |
| TC-DF-T-09-004-04 | Negative | Slack trả 429 với Retry-After 30 | Trigger và đo timing | Backoff 30s; retry success; metric rate_limit tăng |
| TC-DF-T-09-004-05 | Edge | 3 fail liên tiếp (network down) | Trigger | Channel auto-disable; admin notification "channel disabled due to repeated failure" |
| TC-DF-T-09-004-06 | Edge | Deep link trỏ campaign đã xóa | User click button | Page hiển thị "Resource not found" rõ ràng, không 404 trắng |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-002.

**Chặn:** DF-T-09-006 (chia template).

**Phụ thuộc giữa Epic:**

- **DF-E-11 (Frontend)** — deep link URL trỏ vào page frontend, schema URL cần đồng bộ.

**Rủi ro:**

- **Slack đổi Block Kit schema** → giảm thiểu: version field trong payload, regression test hàng tháng.
- **Webhook URL lộ trong DB** → giảm thiểu: encrypt at rest, masked trong API response.
- **Rate limit gây delay notification quan trọng** → giảm thiểu: bypass queue cho event severity=critical, priority dispatch.

**Phụ thuộc bên ngoài:** Slack Incoming Webhook API.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả TC-DF-T-09-004-* map sang test tự động.
- [ ] Tài liệu cấu hình Slack đã commit.
- [ ] OpenAPI spec cập nhật.
- [ ] Telemetry: metric `slack_delivery_total`, `slack_rate_limit_total`, `slack_delivery_latency`.
- [ ] Code review ≥ 1 approve.
- [ ] Đã test end-to-end với Slack workspace thật.
- [ ] Release notes cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — mục 5.3 (Webhook delivery), 6 (FR-09-01, FR-09-07, FR-09-13, FR-09-15).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — mục 6 (Webhook Slack Active).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Operator, AI Operations Supervisor.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Webhook, Notification channel.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
