# DF-T-04-010 — Execution runtime trên Temporal workflow

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-010 |
| **Title** | Execution runtime durable trên Temporal workflow + fallback dispatcher |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P0 |
| **Story Points** | 8 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:infra`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-04-05, FR-04-09, FR-04-11, FR-04-12, FR-04-13, FR-04-15, FR-04-20 |
| **Truy vết — UC refs** | UC-04-06, UC-04-08, UC-04-11, UC-04-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đây là **ticket trung tâm** của Epic — execution runtime thật sự chạy scenario trên device. Đặc tả module mục 5.1 vẽ sequence: Dispatch → Workflow (Temporal) → Worker → Executor → Device. Ticket này hiện thực toàn bộ chain đó cho con đường "luồng thành công + một số nhánh lỗi cơ bản". Retry policy, DLQ, pause/resume, capture artifact, audit log đều tách ticket riêng nhưng **integration point ở đây**.

Đặc tả module yêu cầu workflow **durable**: chịu được restart farm, restart worker, network blip. Temporal là chân lý trạng thái workflow. Khi Temporal off, fallback dispatcher in-process vẫn nhận dispatch (FR-04-13) nhưng có giới hạn durability — đặc tả module mục 8 cảnh báo rõ.

Executor đọc chuỗi step, resolve biến (DF-T-04-002), gọi handler theo step family, pre/post capture (DF-T-04-014), checkpoint sau mỗi step thành công. Default stop-on-failure (FR-04-05); chỉ tiếp tục khi error_policy tường minh.

P0, SP 8 — cao nhất Epic. Phụ thuộc gần như mọi ticket trước trong Epic + DF-E-02 (device control), DF-E-06 (artifact store), DF-E-07 (account), DF-E-08 (platform step handler).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** khi tôi dispatch campaign, scenario được executor chạy trên từng device độc lập với durability, mọi tiến độ được lưu, kết quả từng step và artifact đầy đủ
> **Để** workflow không mất tiến độ khi farm restart và tôi truy được nguyên nhân fail mà không phải đọc log infra

Persona phụ: Automation Builder (xem effective_config và step result để debug).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI tạo execution record per device tại dispatch (đã chuẩn bị ở DF-T-04-008) — trace FR-04-11.
- Hệ thống PHẢI khởi tạo Temporal workflow per execution với `workflow_id = exec_{execution_id}`, deterministic — trace FR-04-12.
- Workflow PHẢI execute scenario step-by-step theo flow ở đặc tả module mục 5.4: Resolve biến → Pre capture → Dispatch handler theo family → Post capture → Retry check → Checkpoint → next step.
- Hệ thống PHẢI implement default **stop-on-failure**: step fail (không tìm element, handler trả error retryable=false) → scenario dừng → execution.status=failed → trace FR-04-05.
- Hệ thống PHẢI hỗ trợ `error_policy: ignore` (tiếp tục bỏ qua) và `on_error: <step_id>` (jump tới step recovery) — chỉ kích hoạt khi tường minh — trace FR-04-06, FR-04-20.
- Hệ thống PHẢI ghi checkpoint sau mỗi step thành công vào DB (workflow restart đọc checkpoint resume) — trace FR-04-15.
- Hệ thống PHẢI propagate effective_config (5 tầng) trước mỗi step và log đầy đủ — trace FR-04-09; KPI 100%.
- Hệ thống PHẢI ghi execution.status: `created → running → completed / failed / cancelled`. (dlq_open thuộc DF-T-04-012.)
- Hệ thống PHẢI cung cấp **fallback dispatcher** in-process khi Temporal off (FR-04-13): mark execution với flag `dispatch_source=fallback`, banner cảnh báo, không reject dispatch.
- Hệ thống PHẢI dispatch handler step xuống DF-E-08 registry (cho platform-specific) hoặc native handler (cho 7 family generic).
- Hệ thống PHẢI claim device qua DF-E-02 trước, release sau terminal.
- Hệ thống PHẢI emit step result event (sẽ wire vào DF-T-04-013).
- Hệ thống NÊN expose workflow_id cho debug Temporal UI.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Luồng thành công execution end-to-end**

```
Given campaign C dispatch tới D1, scenario S 5 step (Navigation, Interaction, Verification, Extraction, Verification)
And Temporal available, device D1 online
When dispatch
Then execution E1 created, Temporal workflow started
And 5 step chạy tuần tự
And artifact đính kèm mỗi step (pre/post capture)
And execution.status="completed", duration_ms recorded
And device released after terminal
```

**AC-2: Stop on step fail — default behavior**

```
Given scenario S 3 step, step 2 fail (element không tìm thấy)
And step 2 không khai báo error_policy
When workflow chạy
Then step 2 mark failed (artifact lưu trạng thái UI lúc fail)
And step 3 KHÔNG chạy
And execution.status="failed", failed_step_id="step2"
```

**AC-3: ignore_error tiếp tục**

```
Given step 2 có error_policy="ignore"
And step 2 fail
When workflow chạy
Then step 2 mark failed nhưng marked_ignored=true
And step 3 vẫn chạy
And execution status cuối tuỳ step 3 (completed nếu pass)
```

**AC-4: on_error jump recovery**

```
Given step 2 có on_error="step_recovery"
And step 2 fail
When workflow chạy
Then jump tới step_recovery (skip step 3 sequential)
And từ step_recovery tiếp tục theo flow
```

**AC-5: Workflow durable — restart farm**

```
Given execution E running ở step 3 của 5 step
And farm worker restart
When worker khởi động lại và poll workflow
Then workflow resume từ step 3 (qua checkpoint), không re-run step 1, 2
And execution hoàn thành như bình thường
And artifact step 1, 2 không bị ghi đè
```

**AC-6: Temporal off — fallback dispatcher**

```
Given Temporal service down
When dispatch campaign
Then dispatch không reject; execution tạo với flag dispatch_source="fallback"
And workflow chạy in-process; nếu farm restart trong khi đang chạy, có thể mất tiến độ (best-effort)
And dashboard hiển thị banner "Fallback mode active"
```

**AC-7: No implicit recovery — test guard FR-04-20**

```
Given scenario có step fail không retryable, không khai báo error_policy/on_error
When workflow chạy
Then KHÔNG có path code nào tự retry, KHÔNG fallback account, KHÔNG skip step
And execution fail rõ ràng, audit log không có "auto recovery" entry
```

**AC-8: Effective config logged**

```
Given step 3 dùng ${kw} resolved từ runtime tầng
When step 3 chạy
Then log structured có entry { step_id:"step3", effective_config: {kw:"runtime_kw", ...}, resolution_layers: {kw:"runtime"} }
And mọi step 100% có entry (KPI)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm retry policy mechanism detail — DF-T-04-011.
- KHÔNG bao gồm DLQ — DF-T-04-012.
- KHÔNG bao gồm event stream cho consumer ngoài — DF-T-04-013.
- KHÔNG bao gồm pre/post capture implementation chi tiết — DF-T-04-014.
- KHÔNG bao gồm pause/resume/cancel control — DF-T-04-016.
- KHÔNG bao gồm preview execution — DF-T-04-018.
- KHÔNG bao gồm step handler implementation specific cho Facebook — DF-E-08.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Define `ScenarioWorkflow` (Temporal workflow signature).
- [ ] Define `StepActivity` (Temporal activity wrapping step handler).
- [ ] Implement step dispatcher gọi handler theo registry.
- [ ] Implement checkpoint writer (DB write sau mỗi step success).
- [ ] Implement effective_config logger (KPI 100%).
- [ ] Implement error_policy interpretation (default stop, ignore, on_error).
- [ ] Implement fallback dispatcher in-process.
- [ ] Wire pause/resume/cancel signals (will be activated in DF-T-04-016).
- [ ] **Test guard FR-04-20**: phải có code path test riêng đảm bảo không implicit recovery.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho `GET /executions/{id}`, `GET /executions/{id}/steps`.
- [ ] Schema execution: id, campaign_id, scenario_id, scenario_version, device_id, account_id, status, dispatch_source, started_at, completed_at, failed_step_id, current_step_index.
- [ ] Schema step_result: step_id, status, started_at, ended_at, artifact_refs[], error?.
- [ ] Temporal workflow naming convention doc.

**Database / Migration** (`layer:db`)

- [ ] Bảng `executions`.
- [ ] Bảng `execution_steps` (execution_id, step_id, index, status, started_at, ended_at, error_json, effective_config_json).
- [ ] Index trên (campaign_id, status).

**Infra / DevOps** (`layer:infra`)

- [ ] Helm chart Temporal worker (deployment + autoscale).
- [ ] Task queue config.
- [ ] Banner cảnh báo fallback mode (frontend config flag).
- [ ] Chaos test script: kill Temporal, verify fallback; restart Temporal, verify resume.

**Documentation** (`layer:docs`)

- [ ] Architecture doc `docs/modules/campaigns.md` mục Execution runtime.
- [ ] Operator runbook "What to do when Temporal is down".

**Test** (`layer:test`)

- [ ] Unit test step dispatcher.
- [ ] Integration test với Temporal test server.
- [ ] Chaos test workflow resume sau restart worker.
- [ ] Test guard FR-04-20 (≥ 3 case).
- [ ] e2e test end-to-end campaign dispatch → completed.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-010-01 | Positive | Campaign C scenario 5 step valid, D1 online, Temporal up | Dispatch | Execution completed, 5 step success, artifact đầy đủ, audit effective_config 100% |
| TC-DF-T-04-010-02 | Positive | Step 2 có on_error="recovery_step", step 2 fail | Run | Workflow jump recovery_step, tiếp tục, execution status tuỳ kết quả tiếp |
| TC-DF-T-04-010-03 | Negative | Step 3 fail, không error_policy khai báo | Run | Step 4,5 KHÔNG chạy, execution failed, failed_step_id="step3", artifact step 3 lưu UI snapshot lúc fail |
| TC-DF-T-04-010-04 | Negative | Scenario thiếu account_var nhưng step yêu cầu | Dispatch | Reject ở DF-T-04-009 (không vào runtime) |
| TC-DF-T-04-010-05 | Edge | Worker restart giữa step 3 và step 4 | Restart worker | Workflow resume từ step 4 (checkpoint), step 1-3 không re-run |
| TC-DF-T-04-010-06 | Edge | Temporal off | Dispatch | Execution created dispatch_source="fallback", chạy in-process, banner hiện |
| TC-DF-T-04-010-07 | Edge | 100 execution concurrent trên cùng farm | Dispatch | Mỗi execution có workflow_id riêng, không chia sẻ state runtime |
| TC-DF-T-04-010-08 | Edge | Test guard: scenario thiếu account khai báo, device có primary account | Run | Hệ thống fail explicitly, không dùng primary; audit log không có "auto-fallback account" |
| TC-DF-T-04-010-09 | Positive | Step có set_variable kw="X" rồi step sau dùng ${kw} | Run | Step sau thấy kw="X" (tầng runtime cao nhất) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-001, DF-T-04-002, DF-T-04-003, DF-T-04-006, DF-T-04-007, DF-T-04-008, DF-T-04-009; DF-E-02 (device command transport), DF-E-06 (artifact store API), DF-E-07 (account resolver), DF-E-08 (platform step handler registry).

**Chặn:** DF-T-04-011, DF-T-04-012, DF-T-04-013, DF-T-04-014, DF-T-04-015, DF-T-04-016, DF-T-04-017, DF-T-04-018; DF-E-05 (schedule trigger), DF-E-09 (event consumer), DF-E-10 (MCP run_campaign), DF-E-11 (execution detail UI).

**Phụ thuộc giữa Epic:** Đây là điểm hội tụ — DF-E-02/6/7/8 phải có contract sẵn sàng. Cần kick-off meeting với owner 4 epic.

**Rủi ro:**

- **Temporal version compatibility:** lock Temporal version cụ thể; runbook upgrade.
- **Workflow non-deterministic:** không gọi `now()`, không random trực tiếp; dùng Temporal `workflow.Now()`.
- **Checkpoint write atomic với artifact:** dùng transaction hoặc 2-phase commit; fallback eventually-consistent với deduplication key.
- **Fallback dispatcher không durable:** chỉ best-effort; runbook khuyến cáo không dùng cho campaign SLA cao.
- **Test guard FR-04-20 phá vỡ ở refactor sau:** thêm CI check riêng cho test này.
- **Race condition pause/resume sẽ wire ở DF-T-04-016:** đảm bảo signal endpoint stub có sẵn để DF-T-04-016 wire.

**Phụ thuộc bên ngoài:** Temporal ≥ v1.20, Postgres, DF-E-02 transport bus.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80% trên file thay đổi.
- [ ] Test guard FR-04-20 pass với ≥ 3 case.
- [ ] e2e test 1 device chạy scenario 5 step pass trên staging.
- [ ] Chaos test: Temporal restart trong khi workflow chạy → workflow resume < 60s (KPI).
- [ ] Chaos test: worker restart → workflow resume từ checkpoint không re-run step trước.
- [ ] Effective_config log 100% coverage (KPI).
- [ ] Runbook fallback mode published.
- [ ] Code review ≥ 2 approve (owner Campaigns + 1 dev DF-E-02 hoặc 6).
- [ ] Release notes có entry "Execution Runtime GA".
- [ ] Đã chạy thử trên ≥ 10 device thật ≥ 24h và achieve KPI scenario success ≥ 95%.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — toàn bộ mục 5 và FR-04-05, 09, 11, 12, 13, 15, 20.
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Thuật ngữ:** Execution, Workflow, Activity, Worker, Temporal, Authored scenario flow, UI-gated, Checkpoint.
- **Module 02:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — device command contract.
- **Module 08:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — step handler registry.
