# DF-T-08-001 — Plugin contract: interface parser/handler/scenario lib

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-001 |
| **Title** | Plugin contract — interface parser + handler + scenario lib + content type schema |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | Ready |
| **Labels** | `module:social-ext`, `layer:contract`, `layer:backend`, `type:feature`, `platform:agnostic`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-01, FR-08-02, FR-08-03, FR-08-05, FR-08-12 |
| **Truy vết — UC refs** | UC-08-02, UC-08-05, UC-08-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Cho tới hiện tại, code Facebook đang nằm trải rộng ở các module Campaign / Content / Devices mà không có một interface tường minh để platform thứ hai (TikTok, Threads, Instagram) có thể "cắm vào" theo cùng pattern. Hệ quả là cám dỗ kỹ thuật khi đưa platform mới luôn dẫn về "viết runner riêng" — đi ngược nguyên tắc thiết kế trong đặc tả module mục 2 và 3.

Ticket này cung cấp **contract kỹ thuật rõ ràng** cho một platform extension trong Device Farm: interface parser (parse từ hierarchy/screenshot ra object runtime), interface handler (thực thi action UI-gated), interface scenario library (đăng ký step type platform-specific). Đây là nền móng để mọi platform tiếp theo noi theo cùng pattern, và là gate kỹ thuật để code review từ chối các implementation "runner riêng".

Persona hưởng lợi chính là **Platform Engineer** — họ sẽ implement Facebook trên contract này (ticket DF-T-08-004, DF-T-08-005) và sau đó triển khai TikTok / Threads / Instagram theo cùng template. Persona phụ là **Automation Builder** — họ tiêu thụ contract qua scenario step naming convention nhất quán.

Ticket nằm ở đỉnh dependency graph của DF-E-08 — không có ticket nào khác trong Epic này chạy được trước khi contract này được merge.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một bộ interface tường minh để định nghĩa một platform extension (parser + handler + scenario step lib + content type schema)
> **Để** mọi platform mới đều theo cùng pattern, không sinh ra "runner riêng", và team có gate kỹ thuật khi review code

## 4. Yêu cầu chức năng

- Hệ thống PHẢI expose một interface `PlatformParser` với hợp đồng input/output rõ ràng (hierarchy snapshot + screenshot URL → object runtime đã chuẩn hóa) — trace FR-08-02, FR-08-12.
- Hệ thống PHẢI expose interface `PlatformHandler` để thực thi một step action UI-gated trên app platform (input: device session + step params; output: pass/fail + UI evidence) — trace FR-08-01, FR-08-05.
- Hệ thống PHẢI expose interface `PlatformScenarioLib` để đăng ký step type và extraction strategy theo naming `<platform>_<verb>_<object>` và `<platform>_<data_object>` — trace FR-08-01, FR-08-02.
- Hệ thống PHẢI expose interface `PlatformContentTypeSchema` để khai báo content type qualified `<platform>_<content_object>` và mapping từ object runtime sang content_items + `raw_data` — trace FR-08-03, FR-08-07.
- Hệ thống PHẢI validate naming khi đăng ký — tên sai naming convention bị từ chối ở boot time với mã lỗi rõ ràng — trace FR-08-01, FR-08-02, FR-08-03.
- Hệ thống PHẢI có một golden interface test bảo vệ backward compatibility — bất kỳ thay đổi nào tới contract đều phải tăng version theo SemVer.
- Hệ thống NÊN có một reference implementation (no-op platform) đi kèm contract để test integration và làm template cho platform thật.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Interface khai báo và export đủ 4 thành phần**

```
Given module social-ext đã build xong
And contract package được publish ở phiên bản 1.0.0
When Platform Engineer import contract package
Then 4 interface PlatformParser / PlatformHandler / PlatformScenarioLib / PlatformContentTypeSchema được expose
And mỗi interface có docstring mô tả input/output
And SemVer của contract package là 1.0.0
```

**AC-2: Validate naming convention ở boot time**

```
Given một platform extension đăng ký step type tên "fb_tap_comment_button"
And một platform extension đăng ký step type tên "tapCommentButton" (sai naming)
When Device Farm boot
Then step tên "fb_tap_comment_button" được nhận vào registry
And step tên "tapCommentButton" bị từ chối với mã lỗi PLUGIN_INVALID_NAMING
And error log chỉ rõ pattern kỳ vọng "<platform>_<verb>_<object>"
And Device Farm không boot xong khi có extension sai naming (fail-fast)
```

**AC-3: Golden interface test bảo vệ backward compatibility**

```
Given contract package phiên bản 1.0.0 đã được Facebook extension implement
When ai đó submit PR đổi signature của PlatformParser.parse() (xóa param, đổi return type)
Then golden interface test fail trong CI
And error message chỉ rõ "Contract change requires SemVer major bump"
And PR bị block tự động
```

**AC-4: Reference no-op platform implementation chạy được**

```
Given reference no-op platform đi kèm contract package
When chạy integration test với no-op platform được đăng ký
Then plugin registry nạp no-op platform thành công
And no-op platform expose 1 step type và 1 extraction strategy hợp lệ
And scenario chứa step no-op chạy qua executor không lỗi
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm implementation thật cho Facebook — sẽ xử lý trong DF-T-08-004 và DF-T-08-005.
- KHÔNG bao gồm registry / discovery runtime — sẽ xử lý trong DF-T-08-002.
- KHÔNG bao gồm lifecycle (load / unload / version migration) — sẽ xử lý trong DF-T-08-003.
- KHÔNG bao gồm L3 MCP guardrail interface — đã được loại trừ trong đặc tả module mục 3.2; sẽ xử lý trong DF-T-08-007 cho riêng Facebook.
- KHÔNG bao gồm frontend node contract — sẽ xử lý trong scope frontend của ticket platform-specific tương ứng.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Thiết kế interface `PlatformParser` (input: `HierarchySnapshot`, `ScreenshotRef`, `ScenarioContext`; output: `RuntimeObject`)
- [ ] Thiết kế interface `PlatformHandler` (input: `DeviceSession`, `StepParams`, `ScenarioContext`; output: `StepResult` với evidence)
- [ ] Thiết kế interface `PlatformScenarioLib` (đăng ký step type, extraction strategy)
- [ ] Thiết kế interface `PlatformContentTypeSchema` (mapping object runtime → content_items + raw_data)
- [ ] Cài đặt validator naming `<platform>_<verb>_<object>` và `<platform>_<data_object>` và `<platform>_<content_object>`
- [ ] Cài đặt reference no-op platform

**Contract / API** (`layer:contract`)

- [ ] Tạo package `device_farm.social_ext.contract` với phiên bản 1.0.0
- [ ] Viết schema OpenAPI mô tả runtime object output của parser
- [ ] Viết JSON schema cho step params chung và mở rộng riêng platform
- [ ] Tạo CHANGELOG theo SemVer

**Documentation** (`layer:docs`)

- [ ] Viết `docs/modules/social-ext-contract.md` mô tả interface và cách implement
- [ ] Cập nhật `docs/official_docs/modules/08-social-platform-extensions.md` mục 6 (Functional Spec) nếu interface khác kỳ vọng spec
- [ ] Viết tutorial "Tạo platform extension mới" dùng no-op làm ví dụ

**Test** (`layer:test`)

- [ ] Unit test cho naming validator (positive / negative)
- [ ] Golden interface test snapshot contract — bảo vệ backward compatibility
- [ ] Integration test: nạp no-op platform → đăng ký step → chạy scenario qua executor

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-001-01 | Positive | Contract package v1.0.0 published | Implement no-op platform theo contract, đăng ký 1 step type và 1 strategy | Cả hai được nạp vào registry; boot Device Farm thành công |
| TC-DF-T-08-001-02 | Positive | No-op platform đã nạp | Chạy scenario chứa step no-op `noop_tap_dummy` qua scenario executor | Step chạy thành công; trả về `StepResult` đúng schema; có evidence rỗng hợp lệ |
| TC-DF-T-08-001-03 | Negative | Platform extension khai báo step type "tapCommentButton" (sai naming) | Boot Device Farm | Boot fail-fast với mã lỗi `PLUGIN_INVALID_NAMING`; log chỉ rõ tên kỳ vọng |
| TC-DF-T-08-001-04 | Negative | Platform extension khai báo content type "post" (generic, không qualified) | Boot Device Farm | Boot fail-fast với mã lỗi `PLUGIN_INVALID_CONTENT_TYPE`; log nhắc dùng `<platform>_<content_object>` |
| TC-DF-T-08-001-05 | Edge | Có PR đổi signature `PlatformParser.parse()` mà không tăng major version | Chạy CI | Golden interface test fail; PR bị block với message "Contract change requires SemVer major bump" |
| TC-DF-T-08-001-06 | Edge | Platform extension đăng ký 2 step type cùng tên `fb_tap_comment_button` | Boot Device Farm | Boot fail-fast với mã lỗi `PLUGIN_DUPLICATE_STEP_NAME`; log chỉ ra extension nào đang xung đột |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** Không. Đây là ticket gốc của Epic.

**Chặn:** DF-T-08-002, DF-T-08-003, DF-T-08-004, DF-T-08-005, DF-T-08-008, DF-T-08-010, DF-T-08-012.

**Phụ thuộc giữa Epic:**

- **DF-E-04 (Campaign / Scenario executor)** — interface `PlatformHandler.execute()` phải khớp signature mà scenario executor expect. Cần đối soát với executor contract của DF-E-04 trước khi finalize.
- **DF-E-06 (Content)** — interface `PlatformContentTypeSchema.toContentItem()` phải khớp save_extraction API của Module Content.

**Rủi ro:**

- **Contract drift trong giai đoạn implement đầu** — Facebook (ticket DF-T-08-004/005) có thể yêu cầu thay đổi contract sau khi bắt đầu implement → giảm thiểu bằng cách giữ contract v1.0.0 là "best effort", chấp nhận một lần bump tới v1.1.0 trước khi đóng Epic.
- **Interface quá generic làm platform-specific case khó implement** → giảm thiểu bằng cách review contract với Platform Engineer của Facebook trước khi merge, dùng no-op + dummy Facebook làm sanity check.
- **Naming validator quá chặt block legacy alias** → giải pháp: validator chấp nhận cả canonical (`fb_*`) và legacy alias đã được whitelist tường minh (xem DF-T-08-005).

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage ≥ 80% trên file thay đổi.
- [ ] Tất cả test case TC-DF-T-08-001-* được map sang test tự động.
- [ ] Tài liệu kỹ thuật `docs/modules/social-ext-contract.md` cập nhật.
- [ ] Tài liệu nghiệp vụ `docs/official_docs/modules/08-social-platform-extensions.md` cập nhật nếu thay đổi từ phía nghiệp vụ.
- [ ] Telemetry: metric `plugin_registry_load_total` và log boot-time validation đã có.
- [ ] Code review có ≥ 1 approve từ owner module DF-MOD-08.
- [ ] Release notes / changelog cập nhật với SemVer v1.0.0.
- [ ] Golden interface test snapshot đã commit.
- [ ] Reference no-op platform extension đã có và được dùng làm template trong tutorial.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-01, FR-08-02, FR-08-03, FR-08-05, FR-08-12).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — mục 4.2 (Step type platform-specific).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Platform Engineer.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Platform profile, Extraction strategy, Content type.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — platform expansion track.
