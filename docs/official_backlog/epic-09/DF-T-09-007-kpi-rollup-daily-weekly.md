# DF-T-09-007 — KPI rollup daily/weekly + metric aggregation

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-007 |
| **Title** | KPI rollup daily/weekly — metric aggregation per device / campaign / platform / account, lưu vào OLAP-style table, hỗ trợ unread count |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:db`, `type:feature`, `risk:performance`, `persona:social-data-operator`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-09-04, FR-09-05, FR-09-06, FR-09-11 (Lộ trình → Active) |
| **Truy vết — UC refs** | UC-09-04, UC-09-05, UC-09-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 8 nêu rõ giới hạn: "Phân tích chuyên sâu (BI dashboard, cohort analysis, funnel) — phân tích sâu được thực hiện ngoài hệ thống bằng cách xuất activity log ra warehouse." Nhưng dashboard cơ bản trong Device Farm vẫn cần một số rollup nhanh để hiển thị "hôm nay bao nhiêu campaign chạy / fail", "thiết bị nào fail nhiều", "platform nào kéo dữ liệu nhiều" — đây là phần mới DF-E-09 đẩy từ Lộ trình lên Active.

Ticket này dựng **job rollup daily/weekly** scan activity_log → ghi vào bảng OLAP-style `metric_rollup_daily` / `metric_rollup_weekly` theo dimension (organization, device, campaign, platform, account, event_type), value (count, success_count, fail_count, latency_p50/p95). Đồng thời ticket này build **unread count endpoint** (FR-09-04) tận dụng cùng index pattern; cùng endpoint mark-read/mark-all-read (FR-09-05/06).

Persona hưởng lợi: **Social Data Operator** (xem hôm qua thu được bao nhiêu post), **Fleet Operator** (device nào fail nhiều), **Operator** (unread count trên thanh điều hướng).

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** xem KPI tổng hợp theo ngày/tuần (campaign success, content count, device uptime, account rotation) trên dashboard với độ trễ thấp, và unread count notification nổi bật
> **Để** nắm xu hướng vận hành và biết ngay có việc cần xử lý mà không phải truy vấn activity_log thô

Persona phụ: **Supervisor** (báo cáo tuần cho cấp trên), **Admin** (đối soát volume).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có job rollup daily chạy 00:15 mỗi ngày scan activity_log ngày T-1 → ghi vào `metric_rollup_daily` — Lộ trình → Active.
- Hệ thống PHẢI có job rollup weekly chạy thứ Hai 01:00 scan tuần T-1 → ghi vào `metric_rollup_weekly` — Lộ trình → Active.
- Bảng rollup PHẢI có dimension: organization_id, date (or week_start), resource_type (device/campaign/platform/account/event_type), resource_id, event_type; metric: count, success_count, fail_count, latency_p50/p95 — trace FR-09-11.
- Hệ thống PHẢI cung cấp endpoint `GET /api/notifications/unread-count` trả số notification unread của user hiện tại, p99 < 2s — trace FR-09-04.
- Hệ thống PHẢI cung cấp endpoint `PATCH /api/notifications/{id}/read` idempotent — trace FR-09-05.
- Hệ thống PHẢI cung cấp endpoint `POST /api/notifications/read-all` idempotent — trace FR-09-06.
- Job rollup PHẢI idempotent — re-run cùng ngày không tạo duplicate; dùng upsert theo natural key.
- Job rollup PHẢI có guard performance: hard limit 10 phút/job; report metric `rollup_job_duration_seconds`.
- Hệ thống NÊN expose endpoint truy vấn rollup theo dimension cho dashboard (`GET /api/analytics/rollup?dimension=campaign&from=...&to=...`); chi tiết schema thuộc DF-T-09-008.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Rollup daily đầy đủ dimension**

```
Given activity_log có 10000 entry ngày T-1 với mix event_type và resource_type
When job rollup daily chạy 00:15 ngày T
Then bảng metric_rollup_daily có row tổng hợp cho mỗi (org, date, resource_type, resource_id, event_type)
And count khớp với count thực tế từ activity_log
And job hoàn thành < 10 phút
And metric `rollup_job_duration_seconds` được emit
```

**AC-2: Idempotent re-run**

```
Given job rollup daily đã chạy xong cho ngày T-1
When re-trigger thủ công lại
Then không có row duplicate trong metric_rollup_daily
And upsert theo natural key (org, date, resource_type, resource_id, event_type)
And log thông báo "rollup re-run idempotent"
```

**AC-3: Unread count endpoint nhanh và đúng**

```
Given user U có 12 notification unread, 5 đã read
When GET /api/notifications/unread-count
Then trả 200 với {count: 12}
And response time p99 < 500ms (mục tiêu KPI Epic)
And cập nhật ngay sau khi U mark-read 1 notification (count: 11)
```

**AC-4: Mark all read idempotent**

```
Given user U có 12 notification unread
When POST /api/notifications/read-all
Then trả 200; 12 notification chuyển sang read; unread count = 0
When U gọi lại POST /api/notifications/read-all
Then trả 200; unread count vẫn = 0; không lỗi
```

**AC-5: Job rollup không chặn write path activity_log**

```
Given job rollup đang chạy với 1 triệu activity_log row
When domain module phát event mới qua activity_logger
Then activity_log insert không bị block (job dùng read replica hoặc snapshot)
And event mới vẫn append đúng ngay; chỉ chưa rollup tới ngày T
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm dashboard data API chi tiết với filter/pivot — sẽ ở DF-T-09-008.
- KHÔNG bao gồm export PDF/CSV report — sẽ ở DF-T-09-013.
- KHÔNG bao gồm ad-hoc query API — sẽ ở DF-T-09-014.
- KHÔNG bao gồm BI cohort/funnel — đặc tả module ngoài phạm vi, dùng warehouse export.
- KHÔNG bao gồm retention policy cho rollup table — sẽ ở DF-T-09-012 (mở rộng phạm vi nếu cần).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement job scheduler trigger rollup_daily 00:15, rollup_weekly thứ Hai 01:00
- [ ] Implement `rollup_daily_job` scan activity_log → aggregate → upsert metric_rollup_daily
- [ ] Implement `rollup_weekly_job` đọc daily rollup → aggregate → upsert weekly
- [ ] Implement 3 endpoint: unread-count, mark-read, mark-all-read
- [ ] Query optimizer: hint index, batch insert

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 3 endpoint notification trạng thái
- [ ] Schema metric_rollup_daily / weekly trong response analytics

**Database / Migration** (`layer:db`)

- [ ] Bảng `metric_rollup_daily` (org_id, date, resource_type, resource_id, event_type, count, success_count, fail_count, latency_p50, latency_p95, updated_at)
- [ ] Bảng `metric_rollup_weekly` cùng schema với week_start
- [ ] Index (org_id, date, resource_type), (org_id, resource_id, date) — phục vụ query dashboard
- [ ] Index notifications (recipient_id, status) phục vụ unread count nhanh

**Infra / DevOps** (`layer:infra`)

- [ ] Đăng ký cron job với scheduler (Celery beat / Temporal / k8s CronJob)
- [ ] Alert nếu rollup_job_duration_seconds > 600

**Documentation** (`layer:docs`)

- [ ] Tài liệu schema rollup table
- [ ] Hướng dẫn thêm dimension mới

**Test** (`layer:test`)

- [ ] Unit test aggregation logic
- [ ] Integration test: insert 10k activity_log row → chạy job → verify rollup count đúng
- [ ] Load test unread-count endpoint với 100k notification / user
- [ ] Test idempotent re-run

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-007-01 | Positive | activity_log có 1000 entry ngày T-1 cho 5 campaign | Trigger rollup daily | 5 row trong metric_rollup_daily với count đúng; job < 1 phút |
| TC-DF-T-09-007-02 | Positive | User U có 7 unread | GET /api/notifications/unread-count | 200 {count: 7}; p99 < 500ms |
| TC-DF-T-09-007-03 | Positive | User U có 12 unread | POST /api/notifications/read-all | 200; tất cả chuyển read; unread-count sau = 0 |
| TC-DF-T-09-007-04 | Negative | User V cố mark-read notification của user W (khác recipient) | PATCH /api/notifications/{W_id}/read | 404 (không leak); audit log "cross_user_attempt" |
| TC-DF-T-09-007-05 | Negative | Job rollup gặp DB error giữa chừng | Trigger | Job retry với backoff; row đã insert được giữ; log error structured; alert nếu retry > 3 |
| TC-DF-T-09-007-06 | Edge | Re-run job rollup daily cùng ngày | Trigger 2 lần | Lần 2 idempotent; không duplicate row |
| TC-DF-T-09-007-07 | Edge | activity_log 5 triệu row ngày T-1 | Trigger rollup daily | Job hoàn thành < 10 phút; không OOM; không block insert mới |
| TC-DF-T-09-007-08 | Edge | User U có 0 unread | GET unread-count | 200 {count: 0}; không lỗi |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-001 (activity_log + notifications schema).

**Chặn:** DF-T-09-008 (dashboard data API consume rollup), DF-T-09-009 (alerting rule đọc rollup), DF-T-09-013 (audit trail report dùng rollup).

**Phụ thuộc giữa Epic:**

- **DF-E-01** — service account cho job rollup, scheduler infra.
- **DF-E-11 (Frontend)** — UI tiêu thụ endpoint unread-count, dashboard chart.

**Rủi ro:**

- **Job rollup chạy quá lâu khi activity_log lớn** → giảm thiểu: dùng read replica/snapshot; partition activity_log theo date (làm trong ticket retention DF-T-09-011); chunk processing.
- **Index bloat trên notifications khi mark-all-read hàng loạt** → giảm thiểu: batch update; tracking via metric.
- **Race condition khi job đang chạy mà event mới phát** → giảm thiểu: rollup chỉ scan tới T-1 23:59:59; event ngày T sẽ vào rollup ngày sau.

**Phụ thuộc bên ngoài:** Scheduler infra (Celery beat / k8s CronJob).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Unit test coverage ≥ 80%.
- [ ] Integration test 10k activity_log → rollup pass.
- [ ] Load test 100k notification / user → unread-count p99 < 2s.
- [ ] Job rollup daily đã chạy ổn định 7 ngày liên tiếp trên staging.
- [ ] Migration tạo 2 bảng rollup chạy trên staging.
- [ ] Tài liệu schema rollup committed.
- [ ] Telemetry: `rollup_job_duration_seconds`, `notification_unread_count_query_duration`.
- [ ] Code review ≥ 1 approve owner module + 1 approve DB.
- [ ] Changelog "KPI rollup daily/weekly v1, notification unread count endpoint v1".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md §6 FR-09-04/05/06/11, §7 (Lộ trình → Active)](../../official_docs/modules/09-notifications-and-analytics.md).
- **Nhóm người dùng:** Social Data Operator (§3.1), Fleet Operator (§3.3), Operator các vai trò.
- **Thuật ngữ:** [Unread count](../../official_docs/00-glossary.md), [Activity log](../../official_docs/00-glossary.md), [Domain event](../../official_docs/00-glossary.md).
- **Ticket liên quan:** DF-T-09-001, DF-T-09-008, DF-T-09-009, DF-T-09-012, DF-T-09-013.
