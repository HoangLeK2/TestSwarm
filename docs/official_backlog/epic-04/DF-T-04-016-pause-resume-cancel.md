# DF-T-04-016 — Pause / Resume / Cancel control

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-016 |
| **Title** | Pause / Resume / Cancel execution control (Temporal signals) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | `Done` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-04-17 |
| **Truy vết — UC refs** | UC-04-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

FR-04-17 yêu cầu operator điều khiển workflow đang chạy mà không mất state. Đặc tả module mục 8 ghi rõ: "Cancel không phải undo" — cancel dừng dispatch, không hoàn tác step đã chạy. Pause dừng activity kế tiếp; Resume tiếp tục từ step dừng.

Persona Social Data Operator UC-04-09 cần pause để xử lý sự cố (network device farm, account bị limit) rồi resume mà không phải re-dispatch.

P0 vì là invariant lifecycle. SP 5 — implementation phụ thuộc Temporal signal pattern.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** pause, resume, hoặc cancel campaign/execution đang chạy mà không mất tiến độ đã đạt
> **Để** xử lý sự cố vận hành (device offline cả lô, account bị limit) rồi tiếp tục, hoặc dừng hẳn nếu cấu hình sai

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp `POST /executions/{id}/pause` gửi signal pause tới workflow (Temporal signal).
- Workflow PHẢI tôn trọng pause: hoàn thành step đang chạy (atomic step), sau đó dừng trước step kế tiếp.
- Hệ thống PHẢI cung cấp `POST /executions/{id}/resume` gửi signal resume.
- Hệ thống PHẢI cung cấp `POST /executions/{id}/cancel` body { reason } — cancel chuyển execution sang `cancelled`; signal workflow stop.
- Hệ thống PHẢI cung cấp tương ứng ở campaign-level: `POST /campaigns/{id}/pause|resume|cancel` — fan-out tới mọi execution đang chạy.
- Hệ thống PHẢI release device qua DF-E-02 khi cancel terminal.
- Hệ thống PHẢI ghi audit log (DF-T-04-015) cho mỗi action.
- Hệ thống PHẢI từ chối pause execution đã completed/cancelled/dlq_*: 409 "INVALID_ACTION".
- Hệ thống PHẢI emit event `execution.paused`, `execution.resumed`, `execution.cancelled` (đã có schema từ DF-T-04-013).
- Hệ thống PHẢI đảm bảo idempotent: pause 2 lần liên tiếp → 1 effective state change.
- Hệ thống PHẢI cancel **không undo**: doc rõ trong runbook.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Pause + Resume**

```
Given execution E running step 3 (đang chạy activity)
When POST /executions/E/pause
Then activity step 3 chạy xong (atomic), workflow dừng trước step 4
And E.status="paused", event execution.paused phát
When POST /executions/E/resume sau 10 phút
Then workflow tiếp tục step 4, E.status="running"
```

**AC-2: Cancel — release device**

```
Given execution E running step 2/5, device D1 đã claim
When POST /executions/E/cancel reason="emergency"
Then signal cancel gửi, step 2 đang chạy có thể abort (best-effort)
And E.status="cancelled", cancelled_at set, cancel_reason lưu
And device D1 release qua DF-E-02
And step 3-5 KHÔNG chạy
And audit log entry
```

**AC-3: Campaign-level pause fan-out**

```
Given campaign C có 10 execution running
When POST /campaigns/C/pause
Then 10 signal pause gửi tới 10 workflow
And mỗi execution chuyển paused sau khi step đang chạy xong
And campaign.status="paused" (FSM update — bổ sung state này nếu chưa có ở DF-T-04-007)
```

**AC-4: Pause execution completed bị reject**

```
Given E.status="completed"
When POST /executions/E/pause
Then 409 "INVALID_ACTION" message "Cannot pause completed execution"
```

**AC-5: Idempotent**

```
Given E.status="running"
When POST /executions/E/pause x2 concurrent
Then 1 request 200, 1 request 200 (idempotent), audit log 1 effective state change (hoặc 2 attempt nhưng 1 effective)
```

**AC-6: Resume khôi phục từ checkpoint chính xác**

```
Given E paused tại step 4 (đã success step 1-3)
When resume
Then step 4 start (không re-run 1-3)
And artifact 1-3 không bị overwrite
```

**AC-7: Cancel không undo — guard**

```
Given E cancel sau khi step 2 đã thực thi (post comment social)
When cancel
Then step 2 effect (comment posted) vẫn còn trên platform
And response cancel có warning "Cancel does not undo posted side effects"
And doc runbook cảnh báo
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm undo logic — đặc tả module mục 8 đã loại trừ.
- KHÔNG bao gồm partial cancel (chỉ cancel một số device) — operator phải cancel tổng hoặc per-execution.
- KHÔNG bao gồm pause/resume cấp organization (bulk freeze) — DF-E-05 (schedule freeze) hoặc admin tool.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [x] Define Temporal signal handlers `pauseSignal`, `resumeSignal`, `cancelSignal`.
- [x] Workflow trong DF-T-04-010 phải poll signal giữa step.
- [x] Endpoint REST 3 action × execution + campaign.
- [x] Campaign-level fan-out logic.
- [x] Audit log + event hook.

**Contract / API** (`layer:contract`)

- [x] OpenAPI 6 endpoint (pause/resume/cancel × execution/campaign).
- [x] Mã lỗi: `INVALID_ACTION`, `EXECUTION_NOT_FOUND`.
- [x] Cập nhật state machine campaign: thêm `paused` state.

**Database / Migration** (`layer:db`)

- [x] Cột `pause_signal_received_at`, `cancel_signal_received_at`.

**Documentation** (`layer:docs`)

- [x] Runbook: "Pause vs Cancel — khi nào dùng cái nào".
- [x] Cảnh báo "Cancel does not undo".

**Test** (`layer:test`)

- [x] Test idempotent.
- [x] Test campaign-level fan-out.
- [x] Integration test với Temporal test server.
- [x] Test pause atomic step (step đang chạy hoàn thành).
- [x] Test resume từ checkpoint.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-016-01 | Positive | E running step 3 | Pause + sau 5p resume | Step 3 xong, dừng, sau resume step 4 start; status đúng |
| TC-DF-T-04-016-02 | Positive | E running, device claimed | Cancel | Status="cancelled", device released, audit log |
| TC-DF-T-04-016-03 | Positive | Campaign C 10 execution running | Campaign pause | 10 execution paused, campaign.status="paused" |
| TC-DF-T-04-016-04 | Negative | E completed | Pause | 409 "INVALID_ACTION" |
| TC-DF-T-04-016-05 | Negative | E không tồn tại | Pause | 404 |
| TC-DF-T-04-016-06 | Edge | 2 pause concurrent | Pause x2 | Idempotent, 1 effective transition |
| TC-DF-T-04-016-07 | Edge | Cancel khi step đang chạy step social (post comment) | Cancel | Step có thể đã commit external effect; response warning lộ rõ |
| TC-DF-T-04-016-08 | Edge | Resume sau khi farm restart trong khi paused | Restart + resume | Workflow restore từ Temporal, resume bình thường |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-010 (workflow + signal stub), DF-T-04-007 (FSM cần `paused` state), DF-T-04-015 (audit), DF-T-04-013 (event).

**Chặn:** DF-E-11 (UI control button) — monitor toolbar + per-device workflow controls shipped.

**Rủi ro:**

- **Pause giữa atomic step không phá vỡ semantic:** step phải atomic — định nghĩa trong contract DF-T-04-002.
- **Cancel race với DLQ open:** ưu tiên cancel (user intent rõ ràng).
- **Campaign-level fan-out chậm với 1000 execution:** dùng signal broadcast hoặc async background; user thấy "pausing..." status trong UI.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Integration test pause/resume/cancel pass.
- [ ] Runbook "Pause vs Cancel" published.
- [ ] Telemetry: metric pause/resume/cancel count, time-to-effective.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-17, mục 8 (cancel ≠ undo).
- **Thuật ngữ:** Workflow, Execution.
