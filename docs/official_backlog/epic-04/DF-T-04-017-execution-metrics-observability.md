# DF-T-04-017 — Execution metrics & observability

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-017 |
| **Title** | Execution metrics & observability dashboard (Prometheus + ops dashboard) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:infra`, `type:feature`, `risk:performance` |
| **Truy vết — FR refs** | FR-04-11, FR-04-12, FR-04-16, FR-04-19; Module KPIs mục 9 |
| **Truy vết — UC refs** | UC-04-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 9 đưa ra 9 KPI cần đo. Hiện tại từng ticket trên đã có metric riêng lẻ; ticket này hợp nhất thành **observability story coherent**: Prometheus metric chuẩn, Grafana dashboard mẫu, SLO định nghĩa, alert rule.

Persona: Fleet Operator / Supervisor cần dashboard tổng quan campaign đang chạy. P2 vì không block business — nhưng cần trước khi go-prod B2B SLA.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator / Supervisor
> **Tôi muốn** dashboard tổng quan health của fleet + campaign + DLQ tồn đọng + Temporal/fallback ratio
> **Để** phát hiện sớm bất thường (DLQ tăng vọt, success rate drop, Temporal down dài)

## 4. Yêu cầu chức năng

- Hệ thống PHẢI expose Prometheus metrics:
  - `execution_total{status, organization}` counter
  - `execution_duration_seconds` histogram
  - `step_duration_seconds{step_type}` histogram
  - `step_fail_total{reason, step_type}` counter
  - `dlq_open_count{organization}` gauge
  - `dlq_processed_total{action: retry|close}` counter
  - `campaign_running_count{organization}` gauge
  - `temporal_fallback_active` gauge (0|1)
  - `capture_success_total`, `capture_failure_total`, `capture_throttled_total`
  - `effective_config_log_coverage` gauge (% should = 100)
- Hệ thống PHẢI có Grafana dashboard mẫu với panel cho mỗi KPI.
- Hệ thống PHẢI có alert rule mẫu (Prometheus AlertManager):
  - `success_rate < 90%` cho 1h → alert critical
  - `dlq_open_count > 100` cho 30 phút → alert warning
  - `temporal_fallback_active == 1` cho 10 phút → alert critical
  - `effective_config_log_coverage < 99%` → alert warning
- Hệ thống NÊN expose `/metrics` endpoint chuẩn Prometheus.
- Hệ thống NÊN có distributed tracing (OpenTelemetry) trên workflow execution.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Metrics expose**

```
Given service running
When curl /metrics
Then trả về Prometheus text format với mọi metric ở mục FR
And labels có organization, status, step_type
```

**AC-2: Dashboard hiển thị KPI thật**

```
Given chạy 100 execution
When mở Grafana dashboard
Then thấy success rate, DLQ count, p50/p95/p99 duration, fallback ratio
And data refresh < 30s
```

**AC-3: Alert critical khi success_rate drop**

```
Given success rate < 90% trong 1 giờ
When alert rule evaluate
Then alert critical firing, gửi tới Slack/PagerDuty channel cấu hình
```

**AC-4: Fallback alert**

```
Given Temporal off, fallback mode active 11 phút
When alert evaluate
Then alert critical "Temporal fallback active > 10m"
```

**AC-5: Coverage KPI = 100%**

```
Given run 100 execution với effective_config log
When đo metric
Then gauge effective_config_log_coverage = 1.0 (100%)
And alert không fire
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm log aggregation (ELK) — DF-E-01 / infra.
- KHÔNG bao gồm BI analytic — DF-E-09.
- KHÔNG bao gồm cost analytics — không scope module này.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Wire Prometheus client + register metrics.
- [ ] Instrument key path (execution lifecycle, step dispatch, DLQ).

**Infra / DevOps** (`layer:infra`)

- [ ] Grafana dashboard JSON committed vào repo.
- [ ] Prometheus alert rules YAML.
- [ ] OpenTelemetry trace setup (optional).

**Documentation** (`layer:docs`)

- [ ] Metric catalogue.
- [ ] SLO definition doc.
- [ ] Runbook "What to do when alert fires".

**Test** (`layer:test`)

- [ ] Smoke test /metrics output.
- [ ] Test alert rule logic với Prometheus rule evaluation.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-017-01 | Positive | Service running | GET /metrics | Mọi metric ở FR list xuất hiện |
| TC-DF-T-04-017-02 | Positive | 100 execution run mixed status | Đo dashboard | Success rate đúng, DLQ count đúng, p95 hiển thị |
| TC-DF-T-04-017-03 | Negative | Metric label thiếu `org_id` hoặc `campaign_id` | Scrape /metrics | CI metric-contract fail, metric không được ship |
| TC-DF-T-04-017-04 | Negative | Alert rule cấu hình sai threshold không parse được | Load alert rules | Deploy bị reject với lỗi rule rõ ràng |
| TC-DF-T-04-017-05 | Edge | Effective config log coverage = 98% | Eval alert | Warning firing |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-010, DF-T-04-012, DF-T-04-014, DF-T-04-015.

**Chặn:** SLO management / DF-E-09.

**Rủi ro:**

- **Cardinality high label:** organization_id label có thể explode với 10k org → giới hạn label cho high-cardinality, dùng exemplar.
- **Metric overhead:** sample rate cho histogram nặng.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Metric catalogue + dashboard JSON committed.
- [ ] Alert rules committed + tested.
- [ ] SLO + runbook published.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — mục 9 KPIs.
- **Module 09:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — downstream.
