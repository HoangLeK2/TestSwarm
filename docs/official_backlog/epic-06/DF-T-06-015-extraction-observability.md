# DF-T-06-015 — Extraction observability (metric, log, audit, secret scrub)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-015 |
| **Title** | Extraction observability (metric, log, audit, secret scrub) |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:infra`, `type:feature`, `platform:agnostic`, `persona:platform-engineer`, `coverage:L2`, `risk:auth` |
| **Truy vết — FR refs** | FR-06-14, FR-06-15 |
| **Truy vết — UC refs** | UC-06-10, UC-06-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Module KPI có 4 mục liên quan đến observability: latency p50 hierarchy/OCR/AI; số sự cố leak provider secret = 0/quý; tỷ lệ scenario fail do provider outage < 1%. Module §8 cảnh báo: "hệ thống cũng chưa có cơ chế 'secret filtering' toàn cục cho mọi log trace, nên team vận hành cần cẩn thận khi share output debug ra ngoài tổ chức."

Ticket này gom toàn bộ telemetry chuẩn cho DF-E-06 (metric, log, audit) và đặc biệt là **secret scrubber** chạy ở log layer (Python logging filter) để không bao giờ ghi provider API key vào log, dù lập trình viên có vô tình log object response thô.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** mọi metric/log/audit của extraction pipeline chuẩn hóa và không leak provider secret
> **Để** vận hành đo lường được, debug được, và compliance được kiểm chứng

Persona phụ: Fleet Operator (theo dõi metric latency), Social Data Operator (audit log truy cập artifact).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI emit các metric chuẩn (Prometheus format):
  - `extraction_latency_ms{engine, content_type, result}` histogram.
  - `extraction_total{engine, content_type, result}` counter.
  - `extraction_error_total{engine, error_code}` counter.
  - `content_item_insert_total{content_type, platform}` counter.
  - `artifact_capture_total{kind}` counter.
  - `artifact_storage_bytes_total{org}` gauge.
  - `ai_vision_provider_health{provider}` gauge 0/1.
- Hệ thống PHẢI ghi structured log JSON với field `trace_id, execution_id, step_index, engine, content_type, organization_id`.
- Hệ thống PHẢI có Python logging filter `SecretScrubber` áp regex `sk-[A-Za-z0-9]{20,}`, `AIzaSy[\w-]{30,}`, `Bearer [A-Za-z0-9\._-]+`, `password=\w+`, ... thay bằng `***SCRUBBED***` trước khi flush — trace FR-06-14.
- Hệ thống PHẢI có audit log table `extraction_audit(id, organization_id, user_id, action, target_type, target_id, metadata_json, created_at)` ghi:
  - `extraction_called` mỗi save_extraction step / endpoint trực tiếp.
  - `artifact_accessed` mỗi lần signed URL gen / download.
  - `budget_exceeded` mỗi block.
  - `cross_tenant_attempt` mỗi denied.
- Hệ thống PHẢI có healthcheck endpoint `/health/extraction` báo trạng thái 3 engine + MinIO + DB.
- Hệ thống PHẢI cung cấp script `scripts/audit-secret-scan.py` quét DB content_items, raw_data, log file tìm pattern secret.
- Hệ thống NÊN cung cấp dashboard JSON definition (Grafana) commit vào `docs/operations/grafana/`.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Metric latency hierarchy**

```
Given AI vision call thành công với latency 5000 ms
When call hoàn tất
Then metric extraction_latency_ms{engine=ai, content_type=fb_post, result=success} có bucket count tăng
And Prometheus scrape thấy giá trị
```

**AC-2: Log không chứa secret**

```
Given developer vô ý log object response chứa "Authorization: Bearer sk-abc123..."
When log flush
Then output ghi "Authorization: Bearer ***SCRUBBED***"
And raw secret không xuất hiện trong stdout / log file / log aggregator
```

**AC-3: Audit log save_extraction**

```
Given user U gọi POST /api/devices/{D}/extract/hierarchy persist=true
When call hoàn tất
Then bảng extraction_audit có row mới: action="extraction_called", user_id=U, target_id=execution_id, metadata={engine, content_type, ...}
```

**AC-4: Audit secret scan**

```
Given chạy script audit-secret-scan.py trên DB production
When script hoàn tất
Then output báo cáo 0 match cho pattern OpenAI/Gemini secret
And nếu có match → exit code 1 và liệt kê row id để vận hành xử lý
```

**AC-5: Healthcheck**

```
Given hierarchy + OCR + AI vision + MinIO + DB đều OK
When GET /health/extraction
Then trả 200 với JSON {status:ok, components:{hierarchy:ok, ocr:ok, ai_vision_openai:ok, ai_vision_gemini:ok, minio:ok, db:ok}}
Given AI vision provider OpenAI fail healthcheck
When GET /health/extraction
Then trả 503 với JSON liệt kê component fail
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm log aggregator setup (Loki, ELK) — đó là DF-E-01 platform runtime.
- KHÔNG bao gồm Grafana deployment — chỉ commit JSON definition.
- KHÔNG bao gồm OpenTelemetry tracing (chỉ structured log với trace_id) — đó là lộ trình.
- KHÔNG bao gồm anomaly detection — chỉ metric thô.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `df.observability.metrics` định nghĩa Prometheus collector.
- [ ] Module `df.observability.scrubber` với regex và logging filter.
- [ ] Module `df.observability.audit` với service `AuditLogger.log(action, ...)`.
- [ ] Healthcheck composite endpoint.
- [ ] Hook scrubber vào root logger ở startup.

**Database / Migration** (`layer:db`)

- [ ] Bảng `extraction_audit`.
- [ ] Index (organization_id, created_at), (user_id, created_at), (action, created_at).

**Infra / DevOps** (`layer:infra`)

- [ ] Prometheus scrape config.
- [ ] Grafana dashboard JSON commit `docs/operations/grafana/extraction-overview.json`.
- [ ] Alert rule "AI vision provider health flapping".
- [ ] Cron audit-secret-scan weekly.

**Documentation** (`layer:docs`)

- [ ] "Extraction observability runbook" trong `docs/operations/`.
- [ ] Bảng metric reference.

**Test** (`layer:test`)

- [ ] Unit test scrubber với 10 secret pattern.
- [ ] Test metric emit (test client Prometheus).
- [ ] Test audit log ghi cho 4 action.
- [ ] Test healthcheck với mock component down.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-015-01 | Positive | Pipeline chạy 100 call AI vision | Scrape /metrics | extraction_latency_ms có 100 sample; histogram đủ bucket |
| TC-DF-T-06-015-02 | Positive | save_extraction call | Query extraction_audit | Row mới với action="extraction_called", metadata đầy đủ |
| TC-DF-T-06-015-03 | Negative | Code thử log "sk-test1234567890abcdefghij" | log flush + grep | Output ghi "***SCRUBBED***"; pattern raw không xuất hiện |
| TC-DF-T-06-015-04 | Negative | OpenAI provider fail; Gemini OK | GET /health/extraction | 503; component openai="fail", gemini="ok" |
| TC-DF-T-06-015-05 | Edge | Cron audit-secret-scan trên DB có 1 row content có "AIzaSy..." inject test | Script chạy | Exit code 1; output liệt kê row; alert P0 |
| TC-DF-T-06-015-06 | Edge | 10k metric emit/s | Stress test | Prometheus scrape không miss; latency emit < 10ms p99 |
| TC-DF-T-06-015-07 | Edge | Scrubber với 100 pattern khác nhau | Test fixture | Tất cả pattern bị scrub; không có pattern bypass |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-004, DF-T-06-005, DF-T-06-006, DF-T-06-009 (vì cần các metric point).

**Chặn:** Không (nhưng là điều kiện Epic Done).

**Phụ thuộc giữa Epic:** DF-E-01 (Platform runtime) cung cấp logging/metric infra. DF-E-09 (Notifications) tiêu thụ alert từ metric/healthcheck.

**Rủi ro:**

- **Scrubber false negative — pattern mới của provider không match regex:** giảm thiểu: list maintained, review khi provider thêm format key; audit weekly.
- **Audit log phình to nhanh:** giảm thiểu: retention 1 năm, archive sang cold storage sau đó.

**Phụ thuộc bên ngoài:** Prometheus client lib (Python).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Scrubber test 100% pattern pass.
- [ ] Audit log ghi đúng 4 action.
- [ ] Healthcheck endpoint live.
- [ ] Grafana JSON commit và verify trên staging.
- [ ] Cron audit-secret-scan chạy weekly trên production, log clean.
- [ ] Telemetry chính (xem §4) đã emit đủ.
- [ ] Code review ≥ 1 approve owner module + 1 approve security + 1 approve owner Infra.
- [ ] Changelog + runbook published.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §6 FR-06-14, FR-06-15, §9 KPI](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** Platform Engineer (§3.4), Fleet Operator (§3.3).
- **Thuật ngữ:** [Artifact](../../official_docs/00-glossary.md), [AI vision](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-01, DF-E-09.
