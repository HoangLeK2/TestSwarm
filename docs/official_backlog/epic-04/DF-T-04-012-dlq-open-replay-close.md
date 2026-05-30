# DF-T-04-012 — DLQ: open, replay, close

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-012 |
| **Title** | DLQ (Dead Letter Queue) — open / replay / close lifecycle |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator`, `risk:data-loss` |
| **Truy vết — FR refs** | FR-04-15, FR-04-16, FR-04-19 |
| **Truy vết — UC refs** | UC-04-10, UC-04-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

FR-04-16 yêu cầu execution thất bại không phục hồi được chuyển vào DLQ để retry hoặc đóng. Đặc tả module mục 5.2 vẽ state machine có `failed → dlq_open → running (retry) / dlq_closed (close)`. Đây là điểm dừng có giám sát: hệ thống đã thử retry tự động theo retry policy (DF-T-04-011) nhưng vẫn fail; operator xem xét, retry thủ công hoặc đóng.

Social Data Operator UC-04-10 cần endpoint truy vấn DLQ, xem screenshot tại thời điểm fail (artifact từ DF-T-04-014), quyết định action. FR-04-19 yêu cầu báo cáo step fail chi tiết — DLQ entry mở ra hiển thị đủ thông tin.

P0 vì là cơ chế đảm bảo không "silent loss" — KPI "DLQ entry processed trong 24h ≥ 90%" phụ thuộc.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** xem execution fail trong DLQ, đọc artifact tại điểm fail, và quyết định retry hoặc đóng
> **Để** xử lý chủ động lỗi tạm thời (device offline đã online lại) hoặc đóng nếu là lỗi cấu hình scenario

## 4. Yêu cầu chức năng

- Hệ thống PHẢI tự động chuyển execution từ `failed` sang `dlq_open` khi step fail không phục hồi được (sau khi hết retry policy DF-T-04-011) — trace FR-04-16.
- Hệ thống PHẢI cung cấp `GET /dlq?org=...&campaign_id=...&status=open` trả về list DLQ entry kèm: execution_id, campaign_id, scenario_id, device_id, account_id, failed_step_id, failure_reason, failed_at, artifact refs, retry_count.
- Hệ thống PHẢI cung cấp `GET /dlq/{execution_id}` chi tiết entry — trace FR-04-19.
- Hệ thống PHẢI cung cấp `POST /dlq/{execution_id}/retry` để re-dispatch execution. Retry tạo execution mới với link `replayed_from=<old_execution_id>` và resume từ checkpoint (FR-04-15) hoặc full re-run tuỳ flag `from_checkpoint=true|false`.
- Hệ thống PHẢI đảm bảo retry **idempotent**: nhiều POST retry cùng entry chỉ tạo 1 execution mới (lock entry trạng thái `retrying`).
- Hệ thống PHẢI cung cấp `POST /dlq/{execution_id}/close` body `{ reason }` để đóng DLQ — chuyển status `dlq_closed`.
- Hệ thống PHẢI emit domain event `execution.dlq.opened`, `execution.dlq.replayed`, `execution.dlq.closed`.
- Hệ thống PHẢI cập nhật campaign aggregator: DLQ open vẫn coi là "execution chưa terminal" để campaign giữ status; dlq_closed coi là terminal.
- Hệ thống PHẢI giữ DLQ entry vĩnh viễn (không auto-purge) cho audit — retention policy ở DF-E-09.
- Hệ thống NÊN cho phép bulk retry: `POST /dlq/bulk-retry` body `{ execution_ids }`.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Execution fail → dlq_open**

```
Given execution E1 step 3 fail, retry policy đã hết max_attempts
When workflow finish với status=failed
Then E1 status chuyển dlq_open
And event execution.dlq.opened phát với {execution_id, failure_reason, failed_step_id, artifact_refs}
And metric "step fail to dlq_open" record (KPI < 60s)
```

**AC-2: List DLQ với filter**

```
Given OrgA có 50 entry dlq_open, 20 entry dlq_closed
When user GET /dlq?org=OrgA&status=open&limit=20
Then trả về 20 entry status=open, pagination next_token nếu còn
And response gồm failed_step_id và preview screenshot URL
```

**AC-3: Retry từ checkpoint — luồng thành công**

```
Given DLQ entry E1 step 3 fail (checkpoint at step 2 success)
When POST /dlq/E1/retry body { from_checkpoint: true }
Then execution mới E1' tạo, replayed_from=E1, scenario chạy từ step 3 (skip step 1,2 đã success)
And E1 entry chuyển status "replayed" (link tới E1')
And E1' workflow chạy theo runtime DF-T-04-010
```

**AC-4: Full re-run**

```
Given DLQ entry E1
When POST /dlq/E1/retry body { from_checkpoint: false }
Then E1' chạy lại từ step 1
And artifact step 1, 2 cũ (của E1) không bị overwrite — E1' có artifact riêng
```

**AC-5: Close DLQ — reason scenario bug**

```
Given DLQ entry E1
When POST /dlq/E1/close body { reason: "scenario logic bug, không retry" }
Then E1 status="dlq_closed", closed_by=user, closed_at=now, close_reason lưu
And event execution.dlq.closed phát
And campaign aggregator re-evaluate (có thể chuyển campaign thành failed/completed)
```

**AC-6: Idempotent retry**

```
Given DLQ entry E1 status="open"
When 2 concurrent POST /dlq/E1/retry
Then chỉ 1 execution mới tạo (1 request 200, 1 trả 409 "DLQ_RETRY_IN_PROGRESS")
And E1 lock chuyển "retrying" trước khi unlock thành "replayed"
```

**AC-7: Bulk retry**

```
Given 5 DLQ entry [E1..E5]
When POST /dlq/bulk-retry body { execution_ids: [E1..E5] }
Then 5 execution mới được tạo, response per-id status
And nếu 1 entry đã closed → response ghi rõ skip với reason
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm auto-replay (cron tự động retry DLQ) — operator playbook quyết định.
- KHÔNG bao gồm DLQ analytics dashboard — DF-E-09.
- KHÔNG bao gồm DLQ notification (gửi mail/slack khi có DLQ mới) — DF-E-09.
- KHÔNG bao gồm purge retention — DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `DLQService` orchestrator (open, list, get, retry, close).
- [ ] Wire vào DF-T-04-010 workflow `failed` post-action.
- [ ] Retry: tạo execution mới từ checkpoint hoặc full; gọi lại DF-T-04-010 dispatch.
- [ ] Idempotency lock (DB row lock or Redis lock).
- [ ] Bulk retry endpoint.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI 5 endpoint DLQ.
- [ ] Schema DLQ entry với enriched info (artifact preview URL).
- [ ] Mã lỗi: `DLQ_NOT_FOUND`, `DLQ_RETRY_IN_PROGRESS`, `DLQ_ALREADY_CLOSED`, `DLQ_PERMISSION_DENIED`.
- [ ] Event schema dlq.opened/replayed/closed.

**Database / Migration** (`layer:db`)

- [ ] Cột `dlq_status` (open/closed/replayed) trên `executions` hoặc bảng `dlq_entries` riêng.
- [ ] Cột `closed_by`, `closed_at`, `close_reason`, `replayed_to_execution_id`.
- [ ] Index `(organization_id, dlq_status, failed_at DESC)` cho list query.

**Documentation** (`layer:docs`)

- [ ] Operator playbook: "Khi xử lý DLQ — khi nào retry vs close".
- [ ] Doc relationship campaign ↔ DLQ ↔ aggregator.

**Test** (`layer:test`)

- [ ] Unit test FSM dlq.
- [ ] Integration test full lifecycle.
- [ ] Idempotency test concurrent retry.
- [ ] Test checkpoint resume.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-012-01 | Positive | E1 fail retry exhausted | Workflow finish | E1 dlq_status="open", event phát |
| TC-DF-T-04-012-02 | Positive | E1 dlq_open, checkpoint step 2 OK, step 3 fail | POST retry from_checkpoint=true | E1' tạo, chạy từ step 3 |
| TC-DF-T-04-012-03 | Positive | E1 dlq_open | POST close reason="logic bug" | dlq_status="closed", aggregator re-evaluate campaign |
| TC-DF-T-04-012-04 | Negative | E99 không tồn tại | POST /dlq/E99/retry | 404 "DLQ_NOT_FOUND" |
| TC-DF-T-04-012-05 | Negative | E1 đã dlq_closed | POST retry | 409 "DLQ_ALREADY_CLOSED" |
| TC-DF-T-04-012-06 | Edge | 2 concurrent retry cùng E1 | POST x2 | 1 success, 1 trả 409 "DLQ_RETRY_IN_PROGRESS", chỉ 1 execution mới |
| TC-DF-T-04-012-07 | Edge | Bulk retry 5 entry, 1 đã closed | POST bulk-retry | Response per-id: 4 success, 1 skip "ALREADY_CLOSED" |
| TC-DF-T-04-012-08 | Positive | DLQ entry có artifact step fail | GET /dlq/E1 | Response chứa artifact URLs (refs DF-E-06) |
| TC-DF-T-04-012-09 | Edge | KPI test: từ step fail tới dlq_open | Đo timestamp | < 60s |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-010 (workflow finish trigger), DF-T-04-011 (retry exhausted condition), DF-T-04-014 (artifact attach), DF-T-04-007 (aggregator), DF-E-06 (artifact preview URL).

**Chặn:** DF-E-09 (notification on dlq.opened), DF-E-11 (DLQ UI page).

**Rủi ro:**

- **Retry resume từ checkpoint sai vì runtime state đã thay đổi (UI device khác lúc retry):** doc cảnh báo, recommend full re-run nếu thời gian từ fail > 1h.
- **Bulk retry quá tải dispatch:** rate limit endpoint, max 50/request.
- **Race condition close + retry concurrent:** lock entry; first-come wins, second 409.
- **DLQ phình to:** không purge, sẽ phình; ticket DF-E-09 retention policy.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Idempotency test pass.
- [ ] KPI test "fail → dlq_open < 60s" pass on staging.
- [ ] Operator playbook published.
- [ ] Telemetry: metric DLQ open/retry/close rate.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.
- [ ] E2E test: dispatch scenario fail → DLQ open → retry → completed pass.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-15, FR-04-16, FR-04-19, mục 5.2.
- **Thuật ngữ:** DLQ, Checkpoint, Execution.
- **Nhóm người dùng:** Social Data Operator.
