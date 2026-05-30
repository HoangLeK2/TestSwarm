# DF-T-04-002 — Scenario DSL & step contract (8 step family)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-002 |
| **Title** | Scenario DSL & step contract (8 step family + graph + nested run_scenario) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P0 |
| **Story Points** | 8 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:automation-builder`, `risk:platform-tos` |
| **Truy vết — FR refs** | FR-04-02, FR-04-03, FR-04-04, FR-04-05, FR-04-06, FR-04-08, FR-04-09 |
| **Truy vết — UC refs** | UC-04-01, UC-04-02, UC-04-03, UC-04-04, UC-04-11, UC-04-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 6 đặt ra một yêu cầu cốt lõi: scenario phải có một **DSL** (Domain Specific Language) thống nhất để diễn đạt 8 step family — Navigation, Interaction, Input/Wait, Verification, Variables/Control flow, Composition, Extraction/Content, Platform-specific. Hiện tại team có 8 group này rời rạc trong code; ticket này hợp nhất chúng vào một **step contract** ổn định, có schema rõ ràng, mà cả frontend editor (DF-E-11) và runtime executor (DF-T-04-010) cùng tuân thủ.

Automation Builder cần một ngôn ngữ "viết một lần đoán được hành vi" — họ đọc step contract là biết step có những field gì, error policy đặt ở đâu, retry config đặt ở đâu. Mục 5.4 đặc tả module mô tả step dispatch flow: mỗi step đi qua Resolve biến → Pre capture → Dispatch theo loại → Post capture → Retry → Checkpoint. Step contract phải đủ giàu để executor biết handler nào chạy mà không cần meta-programming.

Đây là ticket nền tảng thứ hai của Epic, ngay sau data model. Tất cả implementation runtime (DF-T-04-010) và validation (DF-T-04-004) phụ thuộc vào contract này. Priority P0, SP 8 — phải split nếu có dấu hiệu vượt 8 SP. Đây là một trong những điểm Device Farm tạo khác biệt nhất so với công cụ test generic: contract step + invariant pre/post capture + UI-gated default.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** có một DSL JSON/YAML thống nhất để khai báo step cho mọi nhóm hành vi (navigation, interaction, ..., platform-specific), kèm error policy và retry policy
> **Để** scenario của tôi được executor diễn dịch chính xác, đoán được hành vi runtime, và tái sử dụng được giữa các campaign

Persona phụ: developer DF-E-08 (Social Platform Extensions) cần contract để đăng ký platform-specific step (`fb_*`).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI định nghĩa step schema với field bắt buộc `id` (unique trong scenario), `type` (enum 8 family + sub-type), `config` (JSON tùy step type), `error_policy` (`stop` mặc định | `ignore` | `on_error`), `retry` (object hoặc null), `pre_capture` (bool, default true), `post_capture` (bool, default true) — trace FR-04-06, FR-04-07, FR-04-14.
- Hệ thống PHẢI hỗ trợ scenario `kind=sequence` (mảng step có thứ tự) và `kind=graph` (node + edge với điều kiện `if_element`, `if_variable`) — trace FR-04-02, FR-04-03.
- Hệ thống PHẢI cho phép step type `run_scenario` (composition) trỏ tới `scenario_id` + `scenario_version` cụ thể; runtime sẽ inline scenario con — trace FR-04-04.
- Hệ thống PHẢI đặt depth limit cho nested `run_scenario` (default 5, configurable per organization) và từ chối ở validation nếu vượt — trace FR-04-04.
- Hệ thống PHẢI giữ default behavior là **stop-on-failure** (UI-gated): step không tìm thấy element bị mark failed → scenario dừng trừ khi có khai báo `error_policy: ignore` hoặc `on_error: <branch>` — trace FR-04-05, FR-04-06, FR-04-20.
- Hệ thống PHẢI hỗ trợ biến trong config step (cú pháp `${var}`) và resolve theo 5 tầng: campaign vars → scenario default → per-device override → account vars → runtime vars (`set_variable`) — trace FR-04-09.
- Hệ thống PHẢI từ chối step type không thuộc 8 family (return mã lỗi cụ thể) — trace FR-04-08.
- Hệ thống PHẢI cho phép DF-E-08 đăng ký step type platform-specific qua registry (extension point), không hardcode `fb_*` vào core — trace FR-04-08.
- Hệ thống NÊN hỗ trợ `on_error: <step_id>` cho nhánh recovery tường minh (jump tới step id khác) — trace FR-04-06.
- Hệ thống PHẢI đảm bảo step id unique trong cùng scenario; trùng id → validation reject.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Scenario sequence với step Interaction — luồng thành công**

```
Given scenario S kind="sequence" body:
  steps: [
    { id: "open_fb", type: "navigation.open_app", config: { package: "com.facebook.katana" } },
    { id: "tap_search", type: "interaction.tap", config: { selector: "id:search_btn" } }
  ]
When user POST /scenarios/S/body
Then 200, body lưu được, step id unique, không lỗi
And scenario có flag `is_runnable=true`
```

**AC-2: Scenario graph với nhánh điều kiện**

```
Given scenario S kind="graph" body có nodes: A, B, C
And edges: A->B condition { if_element: "id:popup_close" }, A->C condition { else: true }
When validate body
Then 200, graph được lưu, mỗi edge có condition rõ ràng
And không có cycle khi không phải vòng lặp có break condition
```

**AC-3: Step type không thuộc 8 family bị reject**

```
Given user POST scenario body chứa step { id:"x", type:"weird_step.do_thing" }
When validation chạy
Then 400 với code "UNKNOWN_STEP_TYPE", response chứa step id "x" và list supported family
And scenario không lưu được
```

**AC-4: Default stop-on-failure — không tự suy diễn recovery**

```
Given scenario S có 3 step liên tiếp [s1, s2, s3], không step nào có error_policy khai báo
When validator check default policy
Then mỗi step có effective error_policy="stop"
And scenario.is_runnable=true, không cảnh báo
And test guard FR-04-20: nếu code path nào sinh implicit retry/recovery → fail unit test
```

**AC-5: Nested run_scenario vượt depth limit**

```
Given depth limit của OrgA = 5
And scenario S0 -> run_scenario S1 -> ... -> S5 -> run_scenario S6 (depth 6)
When validate S0
Then 400 với code "NESTED_DEPTH_EXCEEDED", chỉ rõ chain S0->...->S6
```

**AC-6: Variable resolve thứ tự**

```
Given campaign C có var { keyword: "campaign_kw" }
And scenario S default { keyword: "scenario_kw" }
And per-device override device_X { keyword: "device_kw" }
And runtime trước step T chạy set_variable { keyword: "runtime_kw" }
When executor đọc ${keyword} ở step T
Then giá trị effective = "runtime_kw" (runtime > account > device > scenario > campaign)
And log effective_config tại step T ghi rõ tầng nguồn
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm typed config schema (`type`, `required`, `secret`, `allowed_values`) — lộ trình, ghi rõ trong đặc tả module mục 8.
- KHÔNG bao gồm graph editor frontend — thuộc DF-E-11.
- KHÔNG bao gồm implementation handler cụ thể của từng step family — chỉ định nghĩa contract; handler thuộc DF-T-04-010 + DF-E-08.
- KHÔNG bao gồm diff giữa scenario version — DF-T-04-003.
- KHÔNG bao gồm import/export YAML — DF-T-04-005.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Định nghĩa enum `StepFamily` (8 giá trị) và sub-type cho mỗi family (`navigation.open_app`, `interaction.tap`, ...).
- [ ] Định nghĩa interface `StepHandler` (input, output, có thể fail, có thể retry) để DF-E-08 implement.
- [ ] Tạo `ScenarioBodyValidator` (chỉ check shape, depth, step id unique; semantic validation ở DF-T-04-004).
- [ ] Tạo `StepRegistry` cho dynamic registration step type platform-specific.
- [ ] Tạo `VariableResolver` với 5 tầng và unit test cho thứ tự ưu tiên.
- [ ] Implement depth limit check khi parse nested `run_scenario`.

**Contract / API** (`layer:contract`)

- [ ] Viết JSON Schema chính thức cho scenario body (sequence + graph).
- [ ] Định nghĩa OpenAPI cho `POST /scenarios/{id}/body` và `GET /scenarios/{id}/body`.
- [ ] Định nghĩa contract `StepRegistry.register(type, handler, schema)` cho DF-E-08.
- [ ] Định nghĩa mã lỗi: `UNKNOWN_STEP_TYPE`, `NESTED_DEPTH_EXCEEDED`, `DUPLICATE_STEP_ID`, `INVALID_GRAPH_EDGE`.

**Database / Migration** (`layer:db`)

- [ ] Cột `body_json` trên bảng `scenarios` (đã có từ DF-T-04-001) — chỉ ghi sau khi validate body shape pass.

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/modules/campaigns.md` với spec 8 step family + example mỗi family.
- [ ] Viết step contract reference cho Automation Builder và DF-E-08 dev.

**Test** (`layer:test`)

- [ ] Unit test JSON Schema validator với 20+ fixture.
- [ ] Unit test depth limit (depth 1, 5, 6, 100).
- [ ] Unit test VariableResolver với mọi combination 5 tầng.
- [ ] Unit test `default stop-on-failure` invariant (test guard FR-04-20).
- [ ] Integration test register custom step type qua StepRegistry.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-002-01 | Positive | Scenario S có body sequence 3 step thuộc 3 family khác nhau, step id unique | POST /scenarios/S/body | 200, body lưu, `is_runnable=true`, validator pass |
| TC-DF-T-04-002-02 | Positive | Scenario S graph 5 node với 2 edge có `if_element`, 1 edge `else` | POST body | 200, body lưu, mỗi edge condition được parse đúng |
| TC-DF-T-04-002-03 | Negative | Scenario body có 2 step cùng id "s1" | POST body | 400 code "DUPLICATE_STEP_ID", chỉ rõ step id trùng |
| TC-DF-T-04-002-04 | Negative | Scenario body chứa step type "weird.thing" không trong registry | POST body | 400 code "UNKNOWN_STEP_TYPE", body không lưu |
| TC-DF-T-04-002-05 | Edge | Scenario nested depth = depth_limit + 1 (mặc định 6) | POST body | 400 code "NESTED_DEPTH_EXCEEDED", response chứa chain các scenario id |
| TC-DF-T-04-002-06 | Edge | Scenario chứa step không khai báo error_policy | Validate | Default `stop`, không cảnh báo, executor sẽ dừng khi step fail |
| TC-DF-T-04-002-07 | Edge | Step config tham chiếu ${var} không tồn tại trong bất kỳ tầng nào | Validate (DF-T-04-004 sẽ chặt hơn; ticket này chỉ check shape) | Pass shape; runtime sẽ raise "MISSING_VARIABLE" — không tự sinh default |
| TC-DF-T-04-002-08 | Positive | DF-E-08 register step type "fb_tap_comment_button" với handler stub | Register + POST scenario body dùng type này | 200, step được nhận diện qua registry |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-001 (scenario entity).

**Chặn:** DF-T-04-003, DF-T-04-004, DF-T-04-005, DF-T-04-010, DF-T-04-011, DF-T-04-014, DF-T-04-018; cả DF-E-08 (cần StepRegistry contract).

**Phụ thuộc giữa Epic:** DF-E-08 (Social Platform Extensions) phải agree StepRegistry interface trước khi merge.

**Rủi ro:**

- **Free-form JSON config:** đặc tả module mục 8 đã ghi nhận đây là gap (chưa có typed schema) → ticket này KHÔNG cố giải, chỉ chuẩn bị extension point để typed schema add sau mà không break.
- **Step id conflict trong graph với loop:** nếu graph có vòng lặp, step có thể chạy nhiều lần — phải phân biệt "static step id" với "execution step index". Risk: log/audit dễ confused → giải pháp: artifact và checkpoint dùng tuple (step_id, iteration_index).
- **StepRegistry không thread-safe khi hot-reload:** DF-E-08 có thể register động → dùng copy-on-write registry hoặc lock.
- **Variable resolve 5 tầng dễ sai thứ tự:** đây là contract quan trọng → test exhaustive, log effective_config mỗi step (KPI 100%).

**Phụ thuộc bên ngoài:** JSON Schema validator (ajv hoặc tương đương trong ngôn ngữ project).

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85% (cao hơn mặc định vì đây là contract core).
- [ ] Test guard FR-04-20 (no implicit recovery) có ít nhất 3 case riêng và pass.
- [ ] JSON Schema chính thức được publish vào `docs/contracts/scenario-body.schema.json`.
- [ ] Tài liệu step contract reference được Automation Builder review (≥ 1 người).
- [ ] DF-E-08 owner xác nhận StepRegistry interface đáp ứng nhu cầu `fb_*` step.
- [ ] Telemetry: metric `scenario.body.validate.fail` theo mã lỗi; log effective_config có thể bật/tắt qua config.
- [ ] Code review ≥ 2 approve (owner Campaigns + 1 dev DF-E-08).
- [ ] Release notes có entry "Scenario DSL v1 GA".
- [ ] Đã có ít nhất 3 scenario template demo cho 3 step family khác nhau.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [docs/official_docs/modules/04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — mục 5.3, 5.4, 6 (FR-04-02 đến FR-04-09), mục 7 (ma trận năng lực).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — 8 step family.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Automation Builder.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Step, Step family, UI-gated, Error policy, Retry policy, run_scenario, Authored scenario flow.
- **Đặc tả module social-ext:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — StepRegistry contract.
