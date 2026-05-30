# DF-T-04-007 — Campaign lifecycle FSM

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-007 |
| **Title** | Campaign lifecycle FSM (Draft → Scheduled → Running → Completed → Cancelled) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-04-01, FR-04-17 (cancel hook) |
| **Truy vết — UC refs** | UC-04-06, UC-04-08, UC-04-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Campaign cần một **finite state machine** để bảo toàn invariant: không double-dispatch, không cancel campaign đã completed, không edit campaign đang running. Đặc tả module mục 5.2 cho execution; campaign cũng cần FSM tương tự nhưng khác (campaign chứa nhiều execution).

Trạng thái: **Draft** (mới tạo, có thể edit) → **Scheduled** (đã đặt lịch chạy bởi DF-E-05) → **Running** (đang dispatch, có execution active) → **Completed** (mọi execution terminal) hoặc **Cancelled** (operator cancel) hoặc **Failed** (toàn bộ execution fail và không phục hồi). FSM định nghĩa rõ transition nào hợp lệ.

P0 vì là invariant nghiệp vụ — sai FSM dễ gây double dispatch hoặc race condition.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** campaign có trạng thái rõ ràng và transition được kiểm soát
> **Để** team biết được campaign nào đang dispatch / hoàn thành / cancel mà không phải truy log chi tiết

## 4. Yêu cầu chức năng

- Hệ thống PHẢI định nghĩa enum `CampaignStatus`: `draft`, `scheduled`, `running`, `completed`, `cancelled`, `failed`, `archived`.
- Hệ thống PHẢI tuân thủ transition graph:
  - `draft → scheduled` (khi DF-E-05 attach schedule)
  - `draft|scheduled → running` (khi dispatch)
  - `running → completed` (mọi execution terminal success)
  - `running → failed` (mọi execution terminal failed/dlq_open và không còn pending)
  - `draft|scheduled|running → cancelled` (operator cancel)
  - `completed|failed|cancelled → archived` (soft delete)
- Hệ thống PHẢI từ chối transition không hợp lệ với 409 và mô tả rõ.
- Hệ thống PHẢI ghi lại lịch sử transition (timestamp, actor, reason) vào audit log (chi tiết tại DF-T-04-015).
- Hệ thống PHẢI cấm PATCH body campaign khi status != `draft` (chỉ cho phép sửa metadata không trọng yếu khi `scheduled`).
- Hệ thống PHẢI compute status `completed` vs `failed` dựa trên aggregate execution status (delegated to DF-T-04-010).
- Hệ thống PHẢI emit domain event mỗi transition: `campaign.status.changed` payload `{from, to, reason}`.
- Hệ thống NÊN cho phép operator "force transition" với super-admin role + lý do (audit) cho recovery scenarios.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Draft → Running khi dispatch**

```
Given campaign C status="draft", có scenario_refs + device target (DF-T-04-008)
When dispatch service gọi transition draft→running
Then campaign.status="running", started_at đặt now
And event campaign.status.changed phát {from:"draft", to:"running"}
And cấm PATCH body từ thời điểm này
```

**AC-2: Running → Completed khi tất cả execution xong**

```
Given campaign C running với 10 execution
And 10 execution chuyển trạng thái terminal (8 completed + 2 dlq_closed)
When aggregator (DF-T-04-010) trigger evaluation
Then campaign.status="completed" (vì không còn execution failed open)
And event campaign.status.changed {from:"running", to:"completed"}
```

**AC-3: Running → Failed khi tất cả fail**

```
Given campaign C có 5 execution; toàn bộ chuyển dlq_open
When aggregator evaluate
Then campaign.status="failed"
And event campaign.status.changed {from:"running", to:"failed", reason:"all_executions_dlq_open"}
```

**AC-4: Transition không hợp lệ bị reject**

```
Given campaign C status="completed"
When user POST /campaigns/C/cancel
Then 409 "INVALID_TRANSITION" với message "Cannot cancel from completed"
And status không đổi
```

**AC-5: Cancel từ running**

```
Given campaign C status="running" với 10 execution
When operator POST /campaigns/C/cancel reason="emergency"
Then campaign.status="cancelled"
And signal cancel được gửi tới mọi execution active (DF-T-04-016 xử lý)
And event campaign.status.changed {to:"cancelled", reason:"emergency"}
```

**AC-6: Cấm PATCH body khi running**

```
Given campaign C status="running"
When PATCH /campaigns/C body { scenario_refs: [...] }
Then 409 "CAMPAIGN_LOCKED" message "Campaign body immutable khi status running"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm pause/resume execution-level — DF-T-04-016.
- KHÔNG bao gồm aggregator status từ execution — phối hợp tại DF-T-04-010 (subscribe event).
- KHÔNG bao gồm UI status badge — DF-E-11.
- KHÔNG bao gồm schedule attachment — DF-E-05.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `CampaignFSM` class với transition table.
- [ ] Hook vào endpoint dispatch (DF-T-04-010), cancel, archive.
- [ ] Aggregator listener: subscribe execution status changes, compute campaign status.
- [ ] Force-transition endpoint (super-admin only).

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho `POST /campaigns/{id}/cancel`, `POST /campaigns/{id}/archive`, `POST /campaigns/{id}/force-transition`.
- [ ] Mã lỗi: `INVALID_TRANSITION`, `CAMPAIGN_LOCKED`, `CAMPAIGN_NOT_FOUND`.
- [ ] Event schema `campaign.status.changed`.

**Database / Migration** (`layer:db`)

- [ ] Cột `status`, `started_at`, `completed_at`, `cancelled_at` trên `campaigns`.
- [ ] Index trên status (cho query "campaign running").

**Documentation** (`layer:docs`)

- [ ] Diagram FSM trong `docs/modules/campaigns.md`.

**Test** (`layer:test`)

- [ ] Unit test mọi transition hợp lệ + không hợp lệ.
- [ ] Test aggregator logic: 8 completed + 2 dlq_closed → completed; 5 dlq_open → failed.
- [ ] Test concurrency: 2 cancel cùng lúc → idempotent.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-007-01 | Positive | Campaign C draft | Dispatch | Status="running", event phát, started_at set |
| TC-DF-T-04-007-02 | Positive | C running, 5 execution all completed | Aggregator trigger | Status="completed", completed_at set |
| TC-DF-T-04-007-03 | Negative | C status "completed" | POST /cancel | 409 "INVALID_TRANSITION" |
| TC-DF-T-04-007-04 | Negative | C status "running" | PATCH body | 409 "CAMPAIGN_LOCKED" |
| TC-DF-T-04-007-05 | Edge | C có 0 execution (target device empty sau filter) | Dispatch | Status transition trực tiếp draft → completed (no-op) hoặc failed tuỳ rule — định nghĩa: nếu target_count=0, reject ở dispatch (DF-T-04-008) trước khi đổi status |
| TC-DF-T-04-007-06 | Edge | 2 cancel request concurrent | POST /cancel x2 | Cả hai trả 200 (idempotent), event chỉ phát 1 lần, audit log ghi 2 attempt nhưng 1 effective transition |
| TC-DF-T-04-007-07 | Negative | User không có role super-admin | POST /force-transition | 403 |
| TC-DF-T-04-007-08 | Positive | C cancelled | POST /archive | Status="archived" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-006.

**Chặn:** DF-T-04-008, DF-T-04-010 (dispatch trigger FSM), DF-T-04-016.

**Rủi ro:**

- **Race condition transition concurrent:** dùng optimistic locking (version cột) trên row campaign hoặc DB transaction với row lock.
- **Aggregator chậm:** nếu execution status update đông, aggregator có thể lag → debounce + batch evaluate.
- **Trạng thái `failed` vs `cancelled` mơ hồ khi mix:** quy ước cancel ưu tiên (user intent rõ ràng); nếu chưa cancel mà aggregator thấy all DLQ → `failed`.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%, FSM transition table 100% coverage.
- [ ] Doc FSM diagram updated.
- [ ] Telemetry: metric `campaign.status.transition.count{from,to}`.
- [ ] Concurrency test pass (locust hoặc tương đương).
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-01, FR-04-17, mục 5.2 (state machine execution — campaign là analogous).
- **Thuật ngữ:** Campaign.
