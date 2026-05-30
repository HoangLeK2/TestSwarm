# DF-T-04-004 — Scenario validation pipeline

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-004 |
| **Title** | Scenario validation pipeline (shape + semantic + lint) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-04-02, FR-04-04 (depth), FR-04-08 (step family), FR-04-09 (variable check) |
| **Truy vết — UC refs** | UC-04-01, UC-04-04, UC-04-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

DF-T-04-002 đã định nghĩa step contract + shape validation cơ bản. Tuy nhiên các lỗi cấu hình "khó nhìn" như graph có dead-end, biến tham chiếu không tồn tại ở bất kỳ tầng nào, edge condition lỗi syntax, nested scenario tham chiếu scenario đã archived — không bắt được bằng shape validation đơn thuần. Đặc tả module mục 8 cảnh báo: vì config là free-form JSON, "lỗi cấu hình thường chỉ lộ ở thời điểm chạy".

Ticket này xây dựng **validation pipeline đa tầng**: (1) shape (đã có), (2) semantic (graph reachability, variable scope, scenario reference resolve), (3) lint (best practice warning — không block save nhưng cảnh báo). Automation Builder thấy lỗi ngay khi save, không phải đợi dispatch xong và nhận DLQ 30 phút sau.

P1 vì nó nâng quality nghiêm túc nhưng không block core dispatch. Tốt để build sớm vì nó giảm DLQ traffic và giảm thời gian debug — phục vụ KPI "tỷ lệ scenario chạy thành công ≥ 95%".

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** khi save scenario, hệ thống chạy validation đa tầng và báo cụ thể từng warning + error (kèm step id và lý do)
> **Để** tôi sửa được trước khi dispatch, không tốn execution slot để phát hiện lỗi cấu hình

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp endpoint `POST /scenarios/{id}/validate` chạy validation đầy đủ và trả về list `{ level, code, message, location }`.
- Hệ thống PHẢI có 3 level: `error` (block save), `warning` (cho phép save nhưng cảnh báo), `info` (gợi ý).
- Hệ thống PHẢI check **graph reachability**: mọi node phải reachable từ start; không có dead-end node trừ node terminal (success/fail).
- Hệ thống PHẢI check **variable usage**: mọi `${var}` được dùng trong step phải declared ở ít nhất một tầng (scenario default, hoặc explicit input list của scenario). Báo `error` nếu không declared.
- Hệ thống PHẢI check **scenario reference**: step `run_scenario` trỏ tới scenario_id phải tồn tại, không archived, không vượt depth limit, và (nếu chỉ định) `scenario_version` phải tồn tại.
- Hệ thống PHẢI check **error_policy consistency**: nếu step có `on_error: <step_id>` thì step_id đó phải tồn tại trong cùng scenario.
- Hệ thống PHẢI check **retry config**: `max_attempts` phải ∈ [1, 10]; backoff parameter dương; không retry vô hạn.
- Hệ thống NÊN cảnh báo (level=warning) khi scenario không có Verification step (UI-gated khuyến nghị verify trước khi interaction).
- Hệ thống NÊN cảnh báo khi scenario chứa step social platform tham chiếu account chưa khai báo trong campaign vars (gợi ý FR-04-20: tránh implicit primary account fallback).
- Hệ thống PHẢI lưu kết quả validation gần nhất vào `scenarios.last_validation_summary` để UI hiện badge "valid" / "X warnings" mà không phải re-run.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Scenario hợp lệ — validation pass**

```
Given scenario S body shape valid, mọi biến declared, không nested vượt depth
When POST /scenarios/S/validate
Then 200, response { status: "valid", errors: [], warnings: [], infos: [] }
And scenarios.last_validation_summary updated với "valid"
```

**AC-2: Graph có dead-end node**

```
Given scenario S kind=graph có node Z không có edge in (unreachable)
When validate
Then 200 nhưng response.errors chứa { code: "GRAPH_UNREACHABLE_NODE", location: "node Z" }
And status = "invalid"
And cố ý save body bị reject 400 (nếu là PATCH body), trừ khi user pass force=true
```

**AC-3: Variable không declared**

```
Given step "tap_search" có config { selector: "${magic_var}" }
And magic_var không có trong scenario default, không có trong known account vars, không có set_variable trước
When validate
Then errors chứa { code: "UNDECLARED_VARIABLE", location: "step.tap_search.config.selector", message: "${magic_var} chưa được declared ở tầng nào" }
```

**AC-4: Nested scenario reference invalid**

```
Given step "run_sub" type "run_scenario" trỏ scenario_id "S_missing"
When validate
Then errors chứa { code: "SCENARIO_REF_NOT_FOUND", location: "step.run_sub" }

Given step "run_sub2" trỏ "S2" với version=99 (không tồn tại)
When validate
Then errors chứa { code: "SCENARIO_VERSION_NOT_FOUND" }
```

**AC-5: on_error trỏ step không tồn tại**

```
Given step "s1" có { on_error: "s_recovery" } nhưng không có step nào id="s_recovery" trong scenario
When validate
Then errors chứa { code: "INVALID_ON_ERROR_TARGET", location: "step.s1.on_error" }
```

**AC-6: Warning level — không có Verification step**

```
Given scenario social có 10 step Interaction nhưng không có step type "verification.*"
When validate
Then status="valid", warnings chứa { code: "NO_VERIFICATION_STEP", message: "scenario UI-gated khuyến nghị có ít nhất 1 verification" }
And user vẫn save được
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm typed config schema validation (`required`, `secret`, ...) — lộ trình, vì config vẫn là free-form JSON.
- KHÔNG bao gồm validation runtime device capability (vd scenario có step `fb_*` mà device không cài Facebook) — đó là check ở dispatch (DF-T-04-008).
- KHÔNG bao gồm auto-fix / quick-fix suggestion — UI ticket riêng (DF-E-11).
- KHÔNG bao gồm performance lint (vd scenario quá nhiều step) — ticket DF-T-04-017.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Tạo `ScenarioValidator` orchestrator chạy chain check.
- [ ] Implement check graph reachability (BFS từ start node).
- [ ] Implement variable scope analyzer (parse `${var}` từ config, tra cứu tầng).
- [ ] Implement scenario reference resolver gọi ScenarioRepository.
- [ ] Implement retry/error_policy consistency check.
- [ ] Wire validator vào PATCH /scenarios/{id}/body và `POST /scenarios/{id}/validate` standalone.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI schema cho validation result: array of `{ level, code, message, location, hint? }`.
- [ ] Mã lỗi list documented.

**Database / Migration** (`layer:db`)

- [ ] Cột `last_validation_summary` (JSONB) + `last_validated_at` trên `scenarios`.

**Documentation** (`layer:docs`)

- [ ] Validation rules reference: liệt kê tất cả code với mô tả + ví dụ scenario fix.

**Test** (`layer:test`)

- [ ] Mỗi rule có ≥ 1 positive + 1 negative fixture.
- [ ] Integration test: validate kết hợp 3 rule cùng fire.
- [ ] Performance: validate scenario 500 step phải < 500ms.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-004-01 | Positive | Scenario S valid hoàn toàn | POST /validate | status="valid", errors=[], warnings=[] |
| TC-DF-T-04-004-02 | Positive | Scenario có 1 warning (no verification) nhưng không error | POST /validate | status="valid", warnings có 1 entry, save vẫn được |
| TC-DF-T-04-004-03 | Negative | Scenario graph có node Z unreachable | POST /validate | status="invalid", errors có "GRAPH_UNREACHABLE_NODE" |
| TC-DF-T-04-004-04 | Negative | Step dùng `${undefined_var}` không declared | POST /validate | errors có "UNDECLARED_VARIABLE" với location chính xác |
| TC-DF-T-04-004-05 | Edge | Scenario 500 step, validate phải nhanh | POST /validate | Trả về < 500ms (p95), không timeout |
| TC-DF-T-04-004-06 | Edge | Scenario reference nhau vòng tròn (S1 -> S2 -> S1) | POST /validate scenario S1 | errors có "CIRCULAR_SCENARIO_REFERENCE" — không infinite loop |
| TC-DF-T-04-004-07 | Negative | Step on_error trỏ tới step id không tồn tại | POST /validate | errors có "INVALID_ON_ERROR_TARGET" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-002 (step contract + variable resolver), DF-T-04-003 (versioning để check scenario_version ref).

**Chặn:** DF-T-04-005 (import phải validate trước khi commit), DF-E-11 (UI hiển thị validation result).

**Rủi ro:**

- **Validate đồng bộ làm chậm save:** scenario lớn validate có thể vượt ngưỡng UX → cache last_validation, validate async khi user chưa request immediate.
- **Vòng lặp reference scenario:** dùng cycle detection trong graph reference.
- **False positive warning:** "no verification" có thể không hợp lệ với scenario data-only (extract metadata mà không tap) → cho phép disable rule per scenario qua tag.

## 10. Điều kiện hoàn thành

- [ ] Code merged, pass CI.
- [ ] Unit test coverage ≥ 85% (validator là logic-heavy).
- [ ] Mọi mã lỗi có doc entry.
- [ ] Test performance: scenario 500 step validate < 500ms.
- [ ] Telemetry: metric `scenario.validate.duration_ms`, `scenario.validate.error_code.*`.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-02, FR-04-04, FR-04-08, FR-04-09, mục 8 (limit: typed schema lộ trình).
- **Thuật ngữ:** Step, run_scenario, Per-device override.
