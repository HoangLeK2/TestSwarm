# DF-T-09-008 — KPI dashboard data API + time-series query

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-008 |
| **Title** | KPI dashboard data API — time-series query theo dimension (device / campaign / platform / account / org), endpoint cho DF-E-11 frontend |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:contract`, `type:feature`, `risk:performance`, `persona:social-data-operator`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-09-11 (Lộ trình → Active) |
| **Truy vết — UC refs** | UC-09-10, UC-09-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

DF-E-11 (Frontend & Dashboard) cần endpoint trả KPI tổng hợp đã rollup (DF-T-09-007) ở dạng time-series để vẽ chart "campaign success per day", "device offline per week", "content count by platform". Trước Epic này, frontend phải query trực tiếp activity_log với GROUP BY — chậm và không scale.

Ticket này dựng **endpoint analytics data API** đọc `metric_rollup_daily` / `metric_rollup_weekly` và trả time-series response chuẩn, hỗ trợ filter theo dimension (organization, resource_type, resource_id, event_type), granularity (day/week), khoảng thời gian. Endpoint có response time p95 < 1s cho window 7 ngày (KPI Epic).

Persona hưởng lợi: **Social Data Operator** (xem trend thu thập), **Fleet Operator** (uptime device), **Supervisor** (báo cáo cấp trên). DF-E-11 sẽ tiêu thụ endpoint này.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** query KPI dashboard theo dimension và time range với response nhanh
> **Để** xem chart "Facebook content collected per day last 30 days" không phải chờ 5 phút

Persona phụ: **Fleet Operator** (chart device uptime), **Frontend dev DF-E-11** (consumer API).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp endpoint `GET /api/analytics/timeseries` với param: `dimension` (device/campaign/platform/account/event_type), `resource_id` (optional), `event_type` (optional list), `from`, `to`, `granularity` (day/week) — trace FR-09-11.
- Response PHẢI là array `[{date, count, success_count, fail_count, latency_p50, latency_p95}, ...]`.
- Hệ thống PHẢI enforce organization filter (auto từ JWT) — không thể query org khác.
- Hệ thống PHẢI cap window: max 90 ngày cho granularity day, max 52 tuần cho granularity week; vượt → 400.
- Hệ thống PHẢI giới hạn resource_id list: max 50 — vượt → 400.
- Hệ thống PHẢI có endpoint `GET /api/analytics/summary` trả KPI top-level cho dashboard: campaign success rate 7d, content count 7d, device uptime 7d.
- Response time p95 < 1s cho window 7 ngày (KPI Epic); p95 < 3s cho window 90 ngày.
- Hệ thống PHẢI hỗ trợ pagination khi response > 1000 row (cursor-based).
- Hệ thống NÊN cache top-level summary endpoint (TTL 5 phút) vì dashboard refresh thường xuyên.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Query time-series theo campaign**

```
Given metric_rollup_daily có data 30 ngày cho campaign X
When GET /api/analytics/timeseries?dimension=campaign&resource_id=X&from=2026-04-26&to=2026-05-26&granularity=day
Then 200; response array 30 row
And mỗi row có {date, count, success_count, fail_count, latency_p50, latency_p95}
And response time p95 < 1s
```

**AC-2: Organization isolation**

```
Given user U thuộc org A query campaign X (thuộc org B)
When GET /api/analytics/timeseries?dimension=campaign&resource_id=X
Then 404 (không leak); audit log "cross_tenant_attempt"
And không trả data
```

**AC-3: Window cap**

```
Given user request window 120 ngày với granularity day
When GET /api/analytics/timeseries?from=...&to=...&granularity=day
Then 400 với mã lỗi WINDOW_TOO_LARGE
And message rõ "Max 90 days for day granularity"
```

**AC-4: Summary endpoint cache**

```
Given user U gọi GET /api/analytics/summary lần đầu (cache miss)
When user gọi lại trong vòng 5 phút
Then response trả từ cache; latency < 50ms
And header X-Cache-Status: HIT
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm export PDF/CSV — sẽ ở DF-T-09-013.
- KHÔNG bao gồm ad-hoc free-form query — sẽ ở DF-T-09-014.
- KHÔNG bao gồm UI render chart — DF-E-11 frontend.
- KHÔNG bao gồm alert engine đọc time-series — sẽ ở DF-T-09-009.
- KHÔNG bao gồm pivot bằng nhiều dimension đồng thời — backlog tương lai (chỉ 1 dimension/request trong v1).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement query builder cho rollup table (validate dimension, resource_id list, window)
- [ ] Implement 2 endpoint `/api/analytics/timeseries`, `/api/analytics/summary`
- [ ] Cache layer Redis cho summary (TTL 5 phút), invalidate khi job rollup daily xong
- [ ] Pagination cursor-based khi > 1000 row
- [ ] Organization filter middleware

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 2 endpoint
- [ ] TypeScript types cho frontend (DF-E-11) generate

**Documentation** (`layer:docs`)

- [ ] Tài liệu API + example query cho dashboard
- [ ] Document KPI calculation formula (success_rate = success_count/count)

**Test** (`layer:test`)

- [ ] Unit test query builder + validation
- [ ] Integration test với 30 ngày data thực
- [ ] Load test: 50 concurrent user query
- [ ] Test organization isolation cross-tenant
- [ ] Test window cap, pagination, cache HIT/MISS

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-008-01 | Positive | 30 ngày rollup data cho 5 campaign | GET timeseries dimension=campaign | 200; 30 row mỗi resource; p95 < 1s |
| TC-DF-T-09-008-02 | Positive | Summary endpoint warm cache | GET /analytics/summary 2 lần | Lần 2 cache HIT; latency < 50ms |
| TC-DF-T-09-008-03 | Negative | User org A query resource org B | GET timeseries | 404; audit log; không leak |
| TC-DF-T-09-008-04 | Negative | Window 120 ngày day granularity | GET timeseries | 400 WINDOW_TOO_LARGE |
| TC-DF-T-09-008-05 | Negative | resource_id list 60 phần tử | GET timeseries | 400 TOO_MANY_RESOURCES |
| TC-DF-T-09-008-06 | Edge | 1 ngày không có data | GET timeseries window 7d | Trả 7 row, ngày trống có count=0 (không bỏ ngày) |
| TC-DF-T-09-008-07 | Edge | 50 concurrent user query | Load test | Không lỗi 5xx; p95 < 3s; DB không quá tải |
| TC-DF-T-09-008-08 | Edge | Granularity week, window 52 tuần | GET timeseries | 200; 52 row; response time < 2s |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-007 (rollup table phải có data).

**Chặn:** DF-E-11 (Frontend dashboard) sử dụng endpoint này.

**Phụ thuộc giữa Epic:**

- **DF-E-11 (Frontend)** — consumer chính.
- **DF-E-01** — JWT user + org context.

**Rủi ro:**

- **Performance kém với window lớn** → giảm thiểu: cap window, index trên rollup, pagination.
- **Cache stale** → giảm thiểu: TTL ngắn 5 phút; invalidate khi rollup job xong.
- **Dimension schema thay đổi (thêm device_type)** → giảm thiểu: versioned API contract; backward compat trong cùng major version.

**Phụ thuộc bên ngoài:** Redis cho cache layer.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Unit test coverage ≥ 80%.
- [ ] Load test 50 concurrent user pass.
- [ ] OpenAPI schema generated cho frontend DF-E-11.
- [ ] Tài liệu API committed.
- [ ] Telemetry: `analytics_query_duration_seconds{dimension, granularity}`, cache hit rate.
- [ ] Code review ≥ 1 approve owner module + 1 approve frontend lead (DF-E-11) cho contract.
- [ ] Changelog "Dashboard data API v1".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md §6 FR-09-11, §7 (Lộ trình → Active)](../../official_docs/modules/09-notifications-and-analytics.md).
- **Nhóm người dùng:** Social Data Operator (§3.1), Fleet Operator (§3.3).
- **Thuật ngữ:** [Activity log](../../official_docs/00-glossary.md), [Organization](../../official_docs/00-glossary.md).
- **Ticket liên quan:** DF-T-09-007 (rollup table), DF-T-09-013 (export), DF-T-09-014 (ad-hoc).
- **Epic liên quan:** DF-E-11 (consumer).
