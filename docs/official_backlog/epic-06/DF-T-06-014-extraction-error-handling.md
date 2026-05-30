# DF-T-06-014 — Extraction error handling & retry policy

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-014 |
| **Title** | Extraction error handling & retry policy |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `type:feature`, `platform:agnostic`, `persona:automation-builder`, `coverage:L2`, `risk:performance` |
| **Truy vết — FR refs** | FR-06-01, FR-06-02, FR-06-03 |
| **Truy vết — UC refs** | UC-06-01, UC-06-02, UC-06-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Mỗi engine extraction có lỗi đặc thù: hierarchy có thể trả rỗng khi UI là Canvas; OCR fail khi ảnh quá tối; AI vision rate limit từ provider. Đặc tả module yêu cầu mỗi engine có mã lỗi rõ ràng — không silent fail. Scenario step `save_extraction` áp error policy của scenario (retry, on_error). Ticket này gom error semantics chung cho cả 3 engine, định nghĩa retry policy default + override, và đảm bảo error propagate đúng tới scenario executor.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** mọi lỗi extraction có code và message rõ ràng, kèm retry policy có thể override per step
> **Để** scenario không silent skip dữ liệu và tôi biết chính xác lỗi gì để fix

Persona phụ: Social Data Operator (nhìn báo cáo execution biết bao nhiêu retry / fail).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI định nghĩa hierarchy lỗi chung:
  - `ExtractionError` (base) với code, message, transient (bool), retryable (bool).
  - `EngineUnavailable` (transient=true, retryable=true).
  - `StrategyNotFound` (transient=false, retryable=false).
  - `StrategyMismatch` (transient=false, retryable=false).
  - `AIVisionParseError` (transient=false, retryable=true 1 lần — đã làm ở DF-T-06-005).
  - `AIVisionProviderError` với subtype rate_limit (retryable=true), auth_failed (retryable=false).
  - `CaptureError` (transient=true, retryable=true).
  - `NormalizationError` (transient=false, retryable=false).
- Hệ thống PHẢI có default retry policy: max_retry=2, backoff exponential 2s/4s, only retry if `transient=true && retryable=true`.
- Hệ thống PHẢI cho step `save_extraction` override retry policy qua field `retry` trong step config (max_retry, backoff_ms_base).
- Hệ thống PHẢI emit event mỗi retry: `extraction_retry` với attempt_number, error_code.
- Hệ thống PHẢI ghi `execution_step_log` row mỗi lần fail (kể cả lúc retry).
- Hệ thống PHẢI báo step fail rõ ràng theo authored scenario flow — không silent skip — đồng nhất với đặc tả module DF-E-04.
- Hệ thống NÊN expose `circuit_breaker` per provider: nếu 50 lỗi provider error trong 1 phút → mở circuit 5 phút, AI vision call bị từ chối ngay (failover về engine khác hoặc skip).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Retry transient error rồi success**

```
Given AI vision call gặp 429 rate_limit
And retry policy default (max_retry=2, backoff 2s/4s)
When call thực hiện
Then attempt 1 fail → wait 2s → attempt 2 success
And step trả thành công sau ~2s latency
And event "extraction_retry" emit 1 lần (attempt_number=2)
```

**AC-2: Exhaust retry → fail**

```
Given AI vision call gặp 503 liên tục
When max_retry=2 exhausted
Then step fail với ExtractionMã lỗi="PROVIDER_UNAVAILABLE"
And execution_step_log có 3 row (attempt 1, 2, 3 đều fail)
And scenario executor xử lý theo on_error policy của step
```

**AC-3: Non-retryable error không retry**

```
Given strategy "snap_story" không tồn tại trong registry
When step chạy
Then attempt 1 fail với StrategyNotFound (retryable=false)
And không có retry
And event "extraction_retry" KHÔNG emit
And step fail ngay
```

**AC-4: Circuit breaker mở**

```
Given OpenAI gặp 50 lỗi rate_limit trong 60s
When attempt thứ 51
Then bị reject ngay với "CIRCUIT_OPEN" (không gọi provider)
And metric circuit_open_total tăng
And sau 5 phút circuit half-open thử lại 1 call; success → close
```

**AC-5: Override retry**

```
Given step save_extraction config retry={max_retry:5, backoff_ms_base:1000}
When transient error xảy ra
Then retry tối đa 5 lần với backoff 1s, 2s, 4s, 8s, 16s
And event "extraction_retry" emit 4 lần (attempt 2..5)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm cross-step retry (retry cả scenario) — đó là DF-E-04 scenario executor.
- KHÔNG bao gồm DLQ — đó là DF-E-04 và DF-E-05.
- KHÔNG bao gồm alert tới user khi retry vượt ngưỡng — đó là DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Hierarchy class lỗi.
- [ ] `RetryPolicy` parser từ step config; default fallback.
- [ ] `RetryExecutor` wrap engine call với retry + backoff.
- [ ] Circuit breaker per provider (in-memory state per worker; có thể dùng `pybreaker`).
- [ ] Inject vào CaptureService, OCR, AI vision, save_extraction.

**Contract / API** (`layer:contract`)

- [ ] Step schema mở rộng field `retry`.
- [ ] Mã lỗi list trong OpenAPI.
- [ ] Event `extraction_retry`, `circuit_open`, `circuit_close`.

**Documentation** (`layer:docs`)

- [ ] Bảng mã lỗi + retryable + default policy.
- [ ] Hướng dẫn override retry per step.

**Test** (`layer:test`)

- [ ] Unit test retry với mock transient + non-transient.
- [ ] Test exhaust retry.
- [ ] Test circuit breaker.
- [ ] Integration test với 3 engine.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-014-01 | Positive | OpenAI lần 1 fail 429, lần 2 success | Call AI vision | Step success sau retry; event retry emit 1 lần |
| TC-DF-T-06-014-02 | Positive | OCR lần 1 transient error, lần 2 success | Call OCR | Step success; latency ~2s extra |
| TC-DF-T-06-014-03 | Negative | Strategy không có trong registry | Call hierarchy | Không retry; fail ngay |
| TC-DF-T-06-014-04 | Negative | AI vision auth_failed (key sai) | Call AI vision | Không retry; fail ngay |
| TC-DF-T-06-014-05 | Edge | 50 lỗi rate_limit trong 60s | Call thứ 51 | Circuit open; reject ngay; sau 5 phút half-open |
| TC-DF-T-06-014-06 | Edge | Override max_retry=10 | Transient error 8 lần liên tục | Retry 8 lần; lần 9 success → step success; latency cộng dồn |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-004, DF-T-06-005, DF-T-06-006, DF-T-06-009.

**Chặn:** Không (nhưng là điều kiện để scenario chạy ổn định trên fleet lớn).

**Phụ thuộc giữa Epic:** DF-E-04 (scenario executor on_error policy phải tương thích).

**Rủi ro:**

- **Retry tăng latency và cost (AI vision):** giảm thiểu: max_retry mặc định 2; tài liệu nhắc.
- **Circuit breaker state in-memory per worker → không nhất quán cluster:** giảm thiểu: chấp nhận eventual consistency; v2 có thể chuyển Redis.

**Phụ thuộc bên ngoài:** Lib `tenacity` hoặc `pybreaker`.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Retry test pass với 3 engine.
- [ ] Circuit breaker test pass.
- [ ] Tài liệu mã lỗi + retry policy publish.
- [ ] Telemetry: `extraction_retry_total{engine, error_code, attempt}`, `circuit_open_total{provider}`, `extraction_fail_total{engine, error_code}`.
- [ ] Code review ≥ 1 approve owner module.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §6 FR-06-01/02/03](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Module KPI:** Tỷ lệ scenario fail do AI provider outage < 1% mỗi tháng.
- **Nhóm người dùng:** Automation Builder (§3.2).
- **Thuật ngữ:** [OCR](../../official_docs/00-glossary.md), [AI vision](../../official_docs/00-glossary.md), [Extraction strategy](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-04.
