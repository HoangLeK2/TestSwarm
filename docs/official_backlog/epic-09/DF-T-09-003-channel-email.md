# DF-T-09-003 — Channel: email (SMTP/SES + template i18n)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-003 |
| **Title** | Channel email — SMTP/SES transport, retry policy, template i18n cho event quan trọng |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `type:feature`, `persona:operator`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-09-01, FR-09-02, FR-09-07 |
| **Truy vết — UC refs** | UC-09-01, UC-09-02, UC-09-06, UC-09-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 7 ghi channel email là **Lộ trình** trong release hiện tại — chỉ có in-app + webhook đã Active. DF-E-09 đẩy email lên Active vì pilot org có yêu cầu mạnh: schedule chạy nửa đêm fail → cần email để operator biết sáng hôm sau thay vì phải nhìn dashboard.

Ticket này hiện thực hóa channel email với SMTP transport (mặc định) + SES adapter (cho cluster AWS). Email dùng template i18n (DF-T-09-006) render từ event payload. Có retry policy với exponential backoff (vì email tạm fail là chuyện thường gặp). Channel email cấu hình per org giống channel webhook.

Persona hưởng lợi: **Operator** (đặc biệt người không ngồi trước dashboard 24/7), **Fleet Operator** (device offline nhận email sớm), **Supervisor** (nhận email digest hàng ngày).

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức
> **Tôi muốn** cấu hình channel email cho org và bật cho các event quan trọng
> **Để** Operator nhận thông báo qua email khi không trực dashboard (đặc biệt event đêm/cuối tuần)

## 4. Yêu cầu chức năng

- Hệ thống PHẢI hỗ trợ transport SMTP và SES qua adapter pattern — trace FR-09-01.
- Admin PHẢI tạo channel email với config: từ địa chỉ, transport type, SMTP credentials hoặc SES IAM role ref — trace FR-09-01.
- Hệ thống PHẢI CRUD channel email — trace FR-09-02.
- Khi rule engine resolve event → channel email, hệ thống PHẢI render template i18n và gửi email — trace FR-09-07.
- Hệ thống PHẢI có retry policy với exponential backoff (3 lần, 30s/2min/10min), DLQ khi exhaust.
- Hệ thống PHẢI ghi nhận kết quả delivery (success / bounce / fail) cho audit.
- Hệ thống PHẢI validate địa chỉ email recipient trước khi gửi.
- Channel email bị vô hiệu hóa PHẢI không gửi email mới — trace FR-09-02.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo channel email SMTP**

```
Given admin có role `org-admin`
When admin POST /api/notif/channels với type=email, config={smtp_host, smtp_port, from_address, credentials_ref}
Then channel tạo thành công, trạng thái enabled=true
And ownership = org admin's org
And response 201 với channel_id
```

**AC-2: Email gửi cho event match rule**

```
Given channel email "ops@acme.com" đang bật cho org acme
And rule: schedule.run_failed → notify owner via channels [in-app, email]
When schedule run fail event emit
Then notification in-app tạo
And email render từ template `schedule_run_failed` (vi/en theo locale user)
And email gửi qua SMTP/SES với delivery_status=success
And delivery log ghi nhận
```

**AC-3: Retry khi gửi fail tạm thời**

```
Given SMTP server timeout lần 1
When email gửi
Then retry attempt 2 sau 30s
And nếu fail, retry attempt 3 sau 2 phút
And nếu vẫn fail, retry attempt 4 sau 10 phút
And sau 3 retry exhaust, email vào DLQ; delivery_status=failed; log error
And admin nhận notification "email delivery failed for channel X"
```

**AC-4: Email không gửi cho địa chỉ invalid**

```
Given recipient user có email = "not-an-email"
When notification trigger
Then email validation reject; delivery_status=invalid_address
And không retry; activity_log ghi
And admin nhận warning "invalid recipient email for user X"
```

**AC-5: Channel vô hiệu hóa không gửi email**

```
Given channel email đang bật
When admin PATCH /api/notif/channels/{id} với enabled=false
And event trigger sau khi disable
Then email KHÔNG gửi
And notification in-app vẫn tạo (rule engine resolve in-app vẫn pass)
And activity_log ghi đầy đủ
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm HMAC signing payload — DF-E-09 không scope.
- KHÔNG bao gồm UI quản lý channel — DF-E-11.
- KHÔNG bao gồm email digest (gộp nhiều event 1 email) — sẽ ở DF-T-09-010.
- KHÔNG bao gồm template editor in UI — DF-E-11 + DF-T-09-006.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `EmailDispatcher` với SMTP adapter và SES adapter
- [ ] Implement retry với exponential backoff
- [ ] Implement DLQ cho email
- [ ] Implement email validation
- [ ] Implement channel type=email trong notification_channels schema

**Contract / API** (`layer:contract`)

- [ ] POST/GET/PATCH/DELETE /api/notif/channels (đã có cho webhook, extend cho email)
- [ ] OpenAPI spec config cho email channel

**Database / Migration** (`layer:db`)

- [ ] Extend bảng `notification_channels` với column `type` (in-app, webhook, email) và `config_json`
- [ ] Bảng `email_delivery_log` (channel_id, event_id, recipient, status, attempt, timestamp)

**Infra / DevOps** (`layer:infra`)

- [ ] Helm config cho SMTP credentials (secret)
- [ ] IAM role cho SES (nếu dùng SES)

**Documentation** (`layer:docs`)

- [ ] Tutorial "Cấu hình channel email với SMTP / SES"
- [ ] Troubleshooting email delivery
- [ ] Cập nhật `docs/official_docs/modules/09-notifications-and-analytics.md` mục 7 (ma trận năng lực) chuyển email từ Lộ trình → Active

**Test** (`layer:test`)

- [ ] Unit test EmailDispatcher với mock SMTP/SES
- [ ] Integration test retry logic
- [ ] E2E test: event → notification → email gửi (qua MailHog hoặc SES sandbox)
- [ ] Test bounce / invalid address

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-003-01 | Positive | SMTP server MailHog chạy local, channel cấu hình | Trigger schedule.run_failed event | Email tới MailHog với template đúng, delivery log status=success |
| TC-DF-T-09-003-02 | Positive | SES sandbox + verified email | Trigger campaign.failed event | Email gửi qua SES; delivery log success |
| TC-DF-T-09-003-03 | Negative | SMTP timeout lần 1 và 2, success lần 3 | Trigger event | Retry 2 lần; lần 3 success; delivery log ghi 3 attempts |
| TC-DF-T-09-003-04 | Negative | Recipient email "not-an-email" | Trigger | Reject với invalid_address; không retry; admin warning |
| TC-DF-T-09-003-05 | Negative | Channel disabled | Trigger | Email KHÔNG gửi; in-app notification vẫn tạo |
| TC-DF-T-09-003-06 | Edge | 3 retry exhaust (SMTP down kéo dài) | Trigger | Vào DLQ; delivery_status=failed; admin notification về channel issue |
| TC-DF-T-09-003-07 | Edge | Send 100 email burst | Concurrency test | Tất cả gửi thành công trong < 10s với rate limiting đúng |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-002.

**Chặn:** DF-T-09-006 (template chia sẻ giữa channel).

**Phụ thuộc giữa Epic:**

- **DF-E-01 (Platform & Auth)** — credentials secret management.

**Rủi ro:**

- **SMTP credentials lộ** → giảm thiểu: lưu qua secret manager, không vào DB plaintext.
- **Email volume gây spam complaint** → giảm thiểu: rate limit per channel (default 100/giờ), bật digest cho high-volume event.
- **Bounce rate cao làm SES bị suspend** → giảm thiểu: monitoring bounce metric, auto-disable channel khi bounce > 5%.

**Phụ thuộc bên ngoài:** SMTP server hoặc AWS SES sandbox cho test; SMTP production setup tùy triển khai org.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả TC-DF-T-09-003-* map sang test tự động.
- [ ] Tài liệu cấu hình SMTP/SES đã commit.
- [ ] OpenAPI spec channel email đã commit.
- [ ] Migration extend bảng channels đã chạy staging.
- [ ] Telemetry: metric `email_delivery_total` (by status), `email_delivery_latency`.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi rõ email channel chuyển từ Lộ trình → Active.
- [ ] `docs/official_docs/modules/09-notifications-and-analytics.md` mục 7 cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — mục 6 (FR-09-01, FR-09-02, FR-09-07), mục 7 (channel email Lộ trình), mục 8 (giới hạn).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Admin, Operator.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Notification channel.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — channel email.
