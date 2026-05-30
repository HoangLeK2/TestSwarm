# DF-T-09-005 — Channel: webhook custom (HTTP POST + delivery log)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-005 |
| **Title** | Channel webhook custom — HTTP POST tới endpoint tự định nghĩa, ghi nhận delivery, retry policy mới |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `type:feature`, `persona:admin`, `persona:ai-ops` |
| **Truy vết — FR refs** | FR-09-01, FR-09-02, FR-09-07, FR-09-13 |
| **Truy vết — UC refs** | UC-09-01, UC-09-02, UC-09-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 7 ghi webhook generic là **Active** nhưng mục 8 nêu rõ "**Webhook dispatcher chưa có retry policy chuyên dụng**" — gọi 1 lần, fail là mất. Đặc tả module cũng nêu HMAC signing chưa có (ngoài phạm vi Epic này).

Ticket này nâng cấp channel webhook custom: thêm **retry policy với exponential backoff + DLQ**, ghi nhận delivery rõ hơn, cho phép payload format chuẩn (JSON schema ổn định cho consumer bên ngoài bind), hỗ trợ custom header (vd Bearer token đơn giản cho endpoint phía nhận verify nguồn).

Persona hưởng lợi: **Admin** (tích hợp Device Farm vào hệ thống nội bộ — ITSM, BI), **AI Operations Supervisor** (consume event AI cho audit tool ngoài).

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức
> **Tôi muốn** tạo channel webhook custom HTTP POST tới endpoint nội bộ với retry và delivery log
> **Để** tích hợp event Device Farm vào ITSM / BI / audit tool của tổ chức mà không phải poll dashboard

## 4. Yêu cầu chức năng

- Admin PHẢI tạo channel webhook custom với config: url, custom_headers (key-value), payload_format (default standard) — trace FR-09-01.
- Hệ thống PHẢI CRUD channel webhook — trace FR-09-02.
- Payload PHẢI có schema ổn định: event_type, organization_id, resource_type, resource_id, summary, timestamp, deep_link — trace FR-09-07.
- Hệ thống PHẢI retry với exponential backoff (3 lần: 30s/2min/10min) khi nhận 5xx hoặc timeout.
- Hệ thống PHẢI ghi nhận delivery log (status code, latency, attempt, error nếu có) — trace FR-09-13.
- Hệ thống PHẢI có DLQ khi exhaust retry; admin xem được DLQ.
- Hệ thống PHẢI có timeout hợp lý (30s default, configurable) cho HTTP request.
- Hệ thống NÊN auto-disable channel nếu fail rate > 50% trong window 10 phút.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo channel webhook custom**

```
Given admin có role org-admin
When admin POST /api/notif/channels với type=webhook, config={url: "https://endpoint.example/notif", custom_headers: {Authorization: "Bearer xxx"}}
Then channel tạo, enabled=true
And response 201
```

**AC-2: Webhook gửi với payload chuẩn**

```
Given channel webhook đang bật
And rule resolve event tới channel này
When event campaign.completed emit
Then HTTP POST tới URL channel với:
  - Header Content-Type: application/json
  - Header Authorization: Bearer xxx (custom_header)
  - Body: {event_type, organization_id, resource_type, resource_id, summary, timestamp, deep_link}
And response 2xx coi là success
And delivery log ghi success + latency
```

**AC-3: Retry khi endpoint 5xx**

```
Given endpoint trả 503 lần 1 và 2, success lần 3
When dispatcher gửi
Then retry với backoff 30s, 2min
And lần 3 success
And delivery log ghi 3 attempt, final status=success
```

**AC-4: Vào DLQ khi exhaust retry**

```
Given endpoint trả 503 tất cả 3 attempt
When retry exhaust
Then event vào DLQ
And delivery log final status=failed
And admin nhận notification "webhook channel X has 1 event in DLQ"
And admin xem DLQ qua /api/notif/channels/{id}/dlq
```

**AC-5: Auto-disable khi fail rate cao**

```
Given channel webhook gửi 100 event trong 10 phút, 60 fail
When fail rate > 50%
Then channel auto-disable
And admin nhận warning "webhook channel X auto-disabled due to high failure rate"
And event tiếp theo không gửi qua channel này
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm HMAC signing payload — nêu rõ trong spec mục 8 (Lộ trình khác).
- KHÔNG bao gồm Slack-specific Block Kit — đã ở DF-T-09-004.
- KHÔNG bao gồm Telegram-specific format — webhook generic vẫn dùng được cho Telegram bot.
- KHÔNG bao gồm webhook ingress (Device Farm nhận lệnh từ bên ngoài) — không scope.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Refactor `WebhookDispatcher` thêm retry policy với exponential backoff
- [ ] Implement DLQ cho webhook
- [ ] Implement timeout configurable
- [ ] Implement auto-disable khi fail rate cao
- [ ] Implement payload schema chuẩn

**Contract / API** (`layer:contract`)

- [ ] Document payload schema ổn định
- [ ] OpenAPI spec cho DLQ endpoint
- [ ] Custom_headers field trong channel config

**Database / Migration** (`layer:db`)

- [ ] Bảng `webhook_delivery_log` (channel_id, event_id, attempt, status_code, latency_ms, error, timestamp)
- [ ] Bảng `webhook_dlq` (id, channel_id, event_payload_json, final_status, last_attempt_at)

**Documentation** (`layer:docs`)

- [ ] Tutorial "Tích hợp Device Farm qua webhook"
- [ ] Document payload schema chuẩn
- [ ] Cập nhật `docs/official_docs/modules/09-notifications-and-analytics.md` mục 8 (retry policy chuyển từ Lộ trình → Active)

**Test** (`layer:test`)

- [ ] Unit test retry logic
- [ ] Integration test với mock endpoint
- [ ] E2E test full flow + DLQ
- [ ] Test auto-disable fail rate

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-005-01 | Positive | Endpoint mock chạy local | Trigger event | HTTP POST với payload chuẩn; custom_header gửi đúng; 2xx; delivery log success |
| TC-DF-T-09-005-02 | Positive | Endpoint trả 503 lần 1,2 success lần 3 | Trigger | Retry với backoff; lần 3 success; log 3 attempts |
| TC-DF-T-09-005-03 | Negative | Endpoint trả 503 tất cả 3 lần | Trigger | Vào DLQ; admin nhận warning; DLQ xem qua API |
| TC-DF-T-09-005-04 | Negative | URL invalid (DNS không resolve) | Trigger | Reject với delivery_status=dns_fail; không retry vô tận |
| TC-DF-T-09-005-05 | Edge | Endpoint timeout 35s, default timeout 30s | Trigger | Timeout sau 30s; retry với backoff |
| TC-DF-T-09-005-06 | Edge | 60 fail / 100 trong 10 phút | Trigger sau đó | Channel auto-disable; warning admin |
| TC-DF-T-09-005-07 | Edge | Payload size > 1MB (deep_link và summary lớn) | Trigger | Payload truncate summary; ghi flag truncated=true; gửi vẫn thành công |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-002.

**Chặn:** DF-T-09-006.

**Phụ thuộc giữa Epic:** Không trực tiếp (webhook generic, không phụ thuộc resource cụ thể).

**Rủi ro:**

- **Endpoint phía nhận không idempotent → nhận trùng khi retry** → giảm thiểu: payload có event_id duy nhất, document cho consumer dùng làm idempotency key.
- **DLQ tăng vô hạn → DB grow** → giảm thiểu: retention DLQ 30 ngày, auto-purge.
- **Custom_headers chứa credential lộ qua log** → giảm thiểu: log mask "Authorization" header value.

**Phụ thuộc bên ngoài:** Endpoint phía nhận tùy admin cấu hình.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả TC-DF-T-09-005-* map sang test tự động.
- [ ] Tài liệu payload schema chuẩn đã commit.
- [ ] OpenAPI cập nhật DLQ endpoint.
- [ ] Migration 2 bảng mới đã chạy staging.
- [ ] Telemetry: metric `webhook_delivery_total`, `webhook_retry_total`, `webhook_dlq_size`.
- [ ] Code review ≥ 1 approve.
- [ ] `docs/official_docs/modules/09-notifications-and-analytics.md` mục 8 cập nhật retry policy.
- [ ] Release notes cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — mục 5.3, 6 (FR-09-01, FR-09-07, FR-09-13), mục 8 (retry policy Lộ trình → Active).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Admin, AI Ops Supervisor.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Webhook, DLQ.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — webhook hardening.
