# DF-T-04-011 — Execution retry policy & backoff

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-011 |
| **Title** | Execution retry policy cấp step + exponential backoff + jitter |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-04-07, FR-04-20 |
| **Truy vết — UC refs** | UC-04-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

FR-04-07 yêu cầu retry policy cấp step: số lần retry, backoff, retryable reason. Đặc tả module mục 5.4 ghi rõ retry chỉ kích hoạt khi step **có thể retryable** và **người dựng đã khai báo retry config tường minh**. Default behavior là không retry.

Hiện tại nhiều scenario fail vì lỗi tạm thời (network blip, UI chưa load xong) — Automation Builder muốn khai báo "step này được retry 3 lần với backoff" mà không phải code logic riêng.

Ticket này hiện thực retry: classifier xác định lỗi retryable hay không, backoff (exponential + jitter), max_attempts cap, telemetry. Kết hợp với FR-04-20: nếu user không khai báo retry → KHÔNG tự thêm.

P0 vì FR-04-07 là Must và ảnh hưởng trực tiếp KPI "scenario success rate ≥ 95%".

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** khai báo retry policy ở cấp step (max_attempts, backoff, jitter, retryable_reasons)
> **Để** step tạm fail vì lý do retryable tự retry mà không cần tôi code riêng, nhưng không retry vô tận

## 4. Yêu cầu chức năng

- Hệ thống PHẢI hỗ trợ schema retry trên step: `{ max_attempts: int [1,10], backoff_ms: int, backoff_strategy: "fixed"|"exponential", jitter: 0..1, retryable_reasons: ["timeout","network","element_not_ready"] }`.
- Hệ thống PHẢI classify lỗi step thành `retryable=true|false` dựa trên `error_code` của handler (handler trả ra) + `retryable_reasons` của step.
- Default retryable_reasons gồm: `timeout`, `network`, `element_not_ready` (rỗng tạm thời). Loại trừ: `permission_denied`, `account_unavailable`, `device_offline_permanent`, `script_logic_error`.
- Hệ thống PHẢI áp dụng exponential backoff với jitter: `wait_ms = backoff_ms * 2^(attempt-1) * (1 + random[-jitter, +jitter])`.
- Hệ thống PHẢI cap max_attempts = 10 (validation).
- Hệ thống PHẢI record mỗi attempt vào execution_steps subtable hoặc array attempt: timestamp, error_reason, wait_ms_before_next.
- Hệ thống PHẢI emit metric `step.retry.attempt.count{step_type, reason}`.
- Hệ thống PHẢI sau khi hết max_attempts mà vẫn fail → step mark failed cuối cùng và scenario áp dụng error_policy của step (DF-T-04-010 logic).
- Hệ thống PHẢI cấm retry vô hạn: backoff_ms hữu hạn, không nested retry policy ở scenario-level (chỉ step-level).
- **Test guard FR-04-20**: nếu step KHÔNG khai báo retry, hệ thống KHÔNG tự retry (không có default retry ngầm).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Retry policy hợp lệ — chạy đến khi success**

```
Given step S có retry { max_attempts: 3, backoff_ms: 1000, backoff_strategy: "exponential", jitter: 0.2 }
And lần 1 fail reason="timeout" (retryable), lần 2 fail reason="timeout", lần 3 success
When runtime chạy step S
Then 3 attempt được record
And wait giữa attempt 1-2 ~1000ms ±20%, giữa 2-3 ~2000ms ±20%
And step status="success" cuối cùng
```

**AC-2: Lỗi không retryable — fail ngay**

```
Given step S có retry { max_attempts: 3, retryable_reasons: ["timeout"] }
And lần 1 fail reason="permission_denied" (không retryable)
When runtime chạy
Then KHÔNG retry, step fail ngay, scenario áp dụng error_policy
```

**AC-3: Hết max_attempts vẫn fail**

```
Given step S có max_attempts: 3
And tất cả 3 attempt fail reason="timeout" (retryable)
When runtime chạy
Then 3 attempt record, step status="failed", failure_reason last attempt
And scenario áp dụng error_policy của step (default stop)
```

**AC-4: Không khai báo retry — không retry ngầm (test guard)**

```
Given step S không có field "retry"
And step S fail reason="timeout"
When runtime chạy
Then KHÔNG retry, step fail ngay
And test guard FR-04-20 pass: không có hidden default retry
```

**AC-5: Backoff cap**

```
Given step S retry max_attempts=10, backoff_ms=1000 exponential, không cap
When tính wait attempt 10
Then wait = 1000 * 2^9 = 512000 ms (~8.5 phút)
And hệ thống có upper cap MAX_BACKOFF_MS=60000 (1 phút) — wait capped 60000ms
And metric record cap triggered
```

**AC-6: Jitter dương**

```
Given backoff_ms=1000, jitter=0.5
When tính 1000 wait
Then mỗi wait nằm trong [500, 1500] ms
And distribution không bias (chạy 1000 lần thấy mean ~1000)
```

**AC-7: Validation reject max_attempts > 10**

```
Given user submit scenario body có step retry max_attempts=20
When validate (DF-T-04-004)
Then 400 "RETRY_MAX_ATTEMPTS_OUT_OF_RANGE"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm retry execution-level (cả scenario retry) — đó là DLQ replay (DF-T-04-012).
- KHÔNG bao gồm circuit breaker / adaptive retry — lộ trình.
- KHÔNG bao gồm idempotency key cho external API call (DF-E-08 platform handler tự xử lý).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `RetryPolicy` value object + parser.
- [ ] `ErrorClassifier` map error_code → retryable.
- [ ] `BackoffCalculator` (exponential + jitter + cap).
- [ ] Wire vào StepActivity ở DF-T-04-010.
- [ ] Telemetry hook.
- [ ] **Test guard FR-04-20 unit test**.

**Contract / API** (`layer:contract`)

- [ ] Schema retry trong step.
- [ ] Mã lỗi `RETRY_MAX_ATTEMPTS_OUT_OF_RANGE`, `RETRY_BACKOFF_INVALID`.

**Database / Migration** (`layer:db`)

- [ ] Bảng `execution_step_attempts` hoặc cột JSONB `attempts` trong execution_steps.

**Documentation** (`layer:docs`)

- [ ] Doc retry config syntax + examples.
- [ ] Best-practice doc "khi nào dùng retry, khi nào dùng on_error".

**Test** (`layer:test`)

- [ ] Unit test 7 scenario backoff.
- [ ] Test classifier error type → retryable.
- [ ] Property test jitter distribution.
- [ ] Test guard FR-04-20.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-011-01 | Positive | Step S max=3, fail-fail-success timeout | Run | 3 attempt, status success |
| TC-DF-T-04-011-02 | Positive | Step S max=3, fail reason="permission_denied" | Run | Không retry, step fail ngay |
| TC-DF-T-04-011-03 | Negative | Step S max=3, fail-fail-fail timeout | Run | 3 attempt, step failed, scenario apply error_policy |
| TC-DF-T-04-011-04 | Edge | Step S không có retry config | Run, fail timeout | Không retry, fail ngay (test guard FR-04-20) |
| TC-DF-T-04-011-05 | Edge | backoff_ms=1000 exponential attempt 10 | Tính wait | Capped MAX_BACKOFF_MS=60000ms |
| TC-DF-T-04-011-06 | Edge | jitter=0.5, run 1000 lần | Property test | mean wait ~ backoff_ms, std dev ~ jitter * backoff_ms |
| TC-DF-T-04-011-07 | Negative | Scenario body có step retry max=20 | Validate | 400 "RETRY_MAX_ATTEMPTS_OUT_OF_RANGE" |
| TC-DF-T-04-011-08 | Edge | Step S max=3, attempt 1 fail timeout, attempt 2 fail permission_denied | Run | Attempt 2 không retryable → step fail ngay sau attempt 2 |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-002 (retry schema in step contract), DF-T-04-004 (validate), DF-T-04-010 (runtime).

**Chặn:** DF-T-04-012 (DLQ trigger sau retry exhausted).

**Rủi ro:**

- **Backoff dài làm execution treo:** cap 60s, metric alerting.
- **Classifier sai retryable cho lỗi mới:** doc rõ retryable_reasons explicit, default conservative.
- **Concurrency: 2 attempt cùng lúc:** trong Temporal activity là serial, không race; assert.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 85%.
- [ ] Test guard FR-04-20 pass.
- [ ] Doc retry config + best-practice published.
- [ ] Telemetry metric đầy đủ.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-07, FR-04-20, mục 5.4.
- **Thuật ngữ:** Retry policy, Error policy.
