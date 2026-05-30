# DF-T-01-008 — Observability foundation (log + metric + trace)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-008 |
| **Title** | Observability foundation — structured log, Prometheus metric, OpenTelemetry trace |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:infra`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | Đặc tả module mục 7 lộ trình "Structured logging với request ID và trace ID"; FR-01-09, FR-01-10 (export metric safe mode) |
| **Truy vết — UC refs** | UC-01-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module liệt kê "Structured logging với request ID và trace ID" và "Metric Prometheus, distributed tracing" trong nhóm lộ trình. Đây là ticket triển khai foundation — không phải đầy đủ chi tiết per-module mà là khung dùng chung. Lý do build ở M1: mọi module sau (device, campaign, relay) sẽ generate event và metric — nếu không có khung sẵn, mỗi module tự đặt naming convention thì 6 tháng sau dashboard sẽ là hỗn loạn.

Phạm vi: (1) structured logger (JSON output) với `request_id`, `trace_id`, `user_id`, `org_id`, `route` tự động inject; (2) Prometheus exporter `/metrics` (admin-only hoặc network-restricted) với metric chuẩn (HTTP request count/duration, runtime, DB pool); (3) OpenTelemetry trace span instrument cho HTTP + DB; (4) catalog naming convention; (5) helm chart triển khai stack tham chiếu (Prometheus + Loki + Tempo hoặc tương đương) cho dev/staging.

P1 vì không hard-block release, nhưng các ticket khác (DF-T-01-005 audit, DF-T-01-007 safe mode) đã reference metric của ticket này nên cần xong cùng release.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** mọi log có request_id và trace_id, metric chuẩn export Prometheus, trace span instrument tự động
> **Để** khi debug incident, tôi có thể follow một request từ HTTP qua DB qua background job mà không phải grep từng file riêng

> **Là** SRE
> **Tôi muốn** dashboard "API health" hiển thị p50/p99 latency, error rate, throughput theo route
> **Để** alerting có baseline rõ ràng và on-call có nhanh tín hiệu

## 4. Yêu cầu chức năng

- Hệ thống PHẢI structured logger output JSON với fields: `ts`, `level`, `msg`, `request_id`, `trace_id`, `span_id`, `user_id` (nếu auth), `org_id` (nếu auth), `route`, `module` — trace lộ trình "Structured logging".
- Hệ thống PHẢI middleware tự generate `request_id` (UUID) nếu request không có header `X-Request-Id`; forward downstream.
- Hệ thống PHẢI exporter `/metrics` (Prometheus format) với metric chuẩn: `http_requests_total{method, route, status, org_id}`, `http_request_duration_seconds_bucket`, `db_pool_in_use`, `db_query_duration_seconds`, `runtime_safe_mode`.
- Hệ thống PHẢI OpenTelemetry trace SDK + instrument cho FastAPI + SQLAlchemy.
- Hệ thống PHẢI exporter trace tới collector (OTLP gRPC); config qua env `OTEL_EXPORTER_OTLP_ENDPOINT`.
- Hệ thống PHẢI logger redact list: `password`, `Authorization`, `X-Device-Key`, `refresh_token`, `secret`, `token` (key chứa pattern).
- Hệ thống PHẢI endpoint `/metrics` chỉ accessible từ admin network hoặc auth=admin-platform (không expose public).
- Hệ thống PHẢI naming convention metric: `<module>.<noun>.<verb>_<unit>` (vd `auth.login.duration_ms`).
- Hệ thống PHẢI helm chart subchart hoặc tham chiếu cho stack observability dev/staging (Prometheus + Loki + Tempo hoặc cloud-managed equivalent).
- Hệ thống NÊN dashboard mẫu Grafana JSON committed trong repo `infra/grafana/`.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Log có request_id và trace_id**

```
Given client gửi request với header X-Request-Id: req-abc-123
When backend xử lý request
Then mọi log entry từ request đó có request_id="req-abc-123"
And trace_id (OTel) cũng được inject
And log emit dạng JSON parseable
```

**AC-2: /metrics expose đúng metric chuẩn**

```
Given runtime đã chạy với 1000 request HTTP gần đây
When admin gọi GET /metrics (qua admin network)
Then response 200 text/plain Prometheus format
And có metric "http_requests_total" với labels method, route, status
And có metric "http_request_duration_seconds_bucket" histogram
And có "runtime_safe_mode" gauge value 0 hoặc 1
```

**AC-3: Trace span propagate**

```
Given request đi qua HTTP → DB query → emit audit event
When trace được export tới collector
Then trace có ≥ 3 span: HTTP root, DB query, audit emit
And tất cả span chia sẻ cùng trace_id
And parent-child relationship rõ ràng
```

**AC-4: Redact list active**

```
Given log message chứa "Authorization: Bearer xxx" trong dữ liệu request
When logger emit
Then output có field Authorization=<REDACTED>
And không có chuỗi "Bearer xxx" trong bất kỳ field nào
And test grep file log sau 100 request có Authorization không tìm thấy raw token
```

**AC-5: /metrics protected**

```
Given user thường (member) cố gọi /metrics qua public network
When request đến
Then response 403 hoặc 404 (config tùy chọn)
When admin platform gọi qua admin network hoặc kèm token đặc biệt
Then response 200
```

**AC-6: Dashboard "API health" hoạt động**

```
Given Grafana đã load JSON dashboard "api-health.json"
When SRE mở dashboard
Then panel hiển thị p50/p99 latency theo route, error rate (4xx/5xx), throughput
And dữ liệu cập nhật mỗi 15s
And alert rule "p99 > 2s for 5min" được defined
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm log aggregation infra (Loki/Elasticsearch deploy đầy đủ production-grade) — chỉ tham chiếu config dev/staging.
- KHÔNG bao gồm SIEM integration — defer.
- KHÔNG bao gồm metric chi tiết per-module (device, campaign) — module owner tự emit, ticket này chỉ build framework.
- KHÔNG bao gồm distributed tracing cho async task (Celery propagate context) — nice-to-have, defer hardening.
- KHÔNG bao gồm long-term metric storage (Cortex, Thanos) — DevOps task.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/observability/logging.py` — structlog config, JSON formatter, redact processor.
- [ ] Middleware `RequestIdMiddleware` tự generate/forward X-Request-Id.
- [ ] Module `device_farm/observability/metrics.py` — Prometheus client, metric registry, HTTP middleware instrument.
- [ ] Module `device_farm/observability/tracing.py` — OTel SDK init, FastAPI + SQLAlchemy instrument.
- [ ] Endpoint `/metrics` với protection (admin network IP allowlist hoặc admin-platform role).

**Frontend** (`layer:frontend`)

- [ ] Client gửi X-Request-Id từ frontend (UUID per request) để correlate.

**Contract / API** (`layer:contract`)

- [ ] Document /metrics endpoint trong OpenAPI (mark internal).
- [ ] Naming convention catalog `docs/observability/naming-convention.md`.

**Database / Migration** (`layer:db`)

- [ ] Không có migration.

**Infra / DevOps** (`layer:infra`)

- [ ] Helm subchart hoặc dependency cho Prometheus + Loki + Tempo (dev/staging).
- [ ] Grafana dashboard JSON `infra/grafana/api-health.json`.
- [ ] Alert rule cơ bản: p99 > 2s, error_rate > 5%, safe_mode = 1 > 5min.
- [ ] Helm value `observability.otel_endpoint`, `observability.metrics_allowlist_cidrs`.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/observability.md`.
- [ ] `docs/observability/naming-convention.md`.
- [ ] Runbook "Investigate latency spike" tham chiếu dashboard.

**Test** (`layer:test`)

- [ ] Unit test logger redact với 50 string fixture nhạy cảm.
- [ ] Integration test: gọi route, verify /metrics có count tăng, log có request_id, trace có span.
- [ ] Load test: 1000 req/s, /metrics scrape không bị throttle, OTel trace export không drop > 1%.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-008-01 | Positive | Runtime up | GET /api/me với X-Request-Id: req-xyz | Log entry có request_id="req-xyz", trace_id ≠ null |
| TC-DF-T-01-008-02 | Positive | 100 request đã gọi | GET /metrics (qua admin network) | 200, metric http_requests_total count ≥ 100 |
| TC-DF-T-01-008-03 | Positive | Request đi qua HTTP + DB + audit | Quan sát trace tại collector | Trace có ≥ 3 span linked |
| TC-DF-T-01-008-04 | Negative | User member gọi /metrics qua public | GET /metrics | 403 hoặc 404 |
| TC-DF-T-01-008-05 | Negative | Log message chứa raw token "Bearer abc123" | Logger emit | Output redacted, grep không tìm "abc123" |
| TC-DF-T-01-008-06 | Edge | 10000 req/s sustained 60s | Load test | /metrics scrape pass; OTel trace drop < 1%; app latency p99 không tăng > 5% |
| TC-DF-T-01-008-07 | Edge | OTel collector down | Gọi API bình thường | App không crash, trace export queued/dropped graceful; metric `otel.export.failed_count` tăng |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (runtime).

**Chặn:** DF-T-01-005 (audit metric), DF-T-01-007 (safe mode metric); cross-Epic: DF-T-02-015 (device event stream tracing), DF-T-03-009 (agent log shipper integrate với log pipeline).

**Phụ thuộc giữa Epic:** Mọi DF-E-02-11 emit metric/log theo convention này.

**Rủi ro:**

- **R1 — OTel overhead làm chậm app.** Giảm thiểu: sampling rate cấu hình; default 10% trace export.
- **R2 — /metrics rò leak sensitive label (vd org_id của khách khác).** Giảm thiểu: review label cardinality; org_id chỉ trong metric nội bộ, không export public.
- **R3 — Log volume tăng nhanh do JSON verbose.** Giảm thiểu: log level INFO mặc định, DEBUG chỉ khi cần.

**Phụ thuộc bên ngoài:** OpenTelemetry SDK Python, Prometheus client Python, structlog, Grafana ≥ 10.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] 7 test case automation.
- [ ] Dashboard "API health" deploy trên staging Grafana, đã verify metric chảy.
- [ ] Naming convention doc reviewed.
- [ ] Telemetry: framework đã tự emit; mỗi module sau chỉ cần dùng helper.
- [ ] Redact list grep CI clean.
- [ ] Alert rule baseline deploy staging và đã verify trigger được.
- [ ] Performance: instrumentation overhead < 5% latency baseline.
- [ ] Code review từ Platform Engineer + SRE.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — mục 7 lộ trình "Structured logging với request ID và trace ID".
- **Ma trận năng lực:** "Structured logging với request ID và trace ID" — Lộ trình; ticket này delivers foundation.
- **Nhóm người dùng:** Platform Engineer, SRE.
- **Thuật ngữ:** Request ID, Trace ID.
- **Ticket liên quan:** DF-T-03-009 (agent log shipper sẽ ingest vào pipeline ticket này dựng).
