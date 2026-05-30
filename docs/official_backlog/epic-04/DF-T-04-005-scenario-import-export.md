# DF-T-04-005 — Scenario import/export & template library

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-005 |
| **Title** | Scenario import/export YAML + JSON & template library |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-04-02 (auxiliary) |
| **Truy vết — UC refs** | UC-04-01, UC-04-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi team có nhiều org cùng dùng cùng pattern social (vd "FB-CrawlComments"), việc copy scenario giữa org hoặc share template từ team Product không thể làm qua UI lẻ tẻ. Ticket này cung cấp **import/export** scenario qua file YAML/JSON và một **template library** chứa scenario mẫu để onboarding Automation Builder mới.

Đặc tả module mục 8 lưu ý: "nên viết template scenario có ví dụ rõ ràng để Automation Builder mới tra cứu". Ticket này hiện thực điều đó.

P2 vì không block core dispatch — sản phẩm vẫn chạy được không có nó, nhưng đây là tool năng suất quan trọng. Đánh giá lại P1 nếu Onboarding KPI yêu cầu.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** export scenario thành file YAML hoặc JSON, import vào org khác, và browse template library để clone scenario mẫu
> **Để** tái sử dụng pattern proven giữa các team và onboarding nhanh hơn

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp `GET /scenarios/{id}/export?format=yaml|json` trả về file payload chứa: metadata + body của version chỉ định (default current_version).
- Hệ thống PHẢI cung cấp `POST /scenarios/import` nhận multipart file YAML/JSON; trả về scenario_id mới.
- Hệ thống PHẢI chạy DF-T-04-004 validation trên scenario import; nếu fail → reject, không tạo scenario.
- Hệ thống PHẢI scrub `organization_id`, `created_by` khi export (privacy), điền lại từ user request khi import.
- Hệ thống PHẢI cho phép import bao gồm dependency `run_scenario` — hoặc resolve theo `scenario_name` (tạo missing), hoặc trả về danh sách missing scenario để user xử lý.
- Hệ thống PHẢI cung cấp namespace `templates` (read-only, owned by org `__system`) chứa template officially-blessed.
- Hệ thống PHẢI cho phép clone template: `POST /scenarios/templates/{template_id}/clone` → tạo scenario mới trong org của user.
- Hệ thống PHẢI giữ payload tương thích ngược: export hôm nay phải import được tháng sau (semver cho schema export).
- Hệ thống NÊN gắn checksum vào payload export để detect manual edit phá format.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Export — luồng thành công**

```
Given scenario S thuộc OrgA, current_version=3
When GET /scenarios/S/export?format=yaml
Then 200, Content-Type yaml, payload chứa metadata (name, description, tags, kind) + body version 3 + schema_version
And organization_id, created_by không có trong payload
```

**AC-2: Import — luồng thành công**

```
Given file YAML hợp lệ chứa scenario "X" version 1
When user OrgB POST /scenarios/import file
Then 201, scenario_id mới trong OrgB, status="draft", current_version=1
And validation DF-T-04-004 đã pass trước khi commit
```

**AC-3: Import fail validation**

```
Given file YAML chứa scenario có graph dead-end
When import
Then 400, response chứa danh sách validation errors
And không có scenario mới được tạo
```

**AC-4: Clone template**

```
Given template T1 trong namespace __system (read-only)
When OrgA user POST /scenarios/templates/T1/clone với body { name_override: "MyClone" }
Then 201, scenario mới trong OrgA tên "MyClone", current_version=1, status="draft"
And template T1 không bị thay đổi
```

**AC-5: Import có dependency missing**

```
Given scenario import S0 có step run_scenario tới scenario_name="S_dep" không tồn tại trong org đích
When import
Then mặc định 400 với "MISSING_SCENARIO_REFERENCES" và list ["S_dep"]
And nếu user pass query param resolve=create_stub, hệ thống tạo S_dep stub (empty body, status=draft) và scenario_id mới được fill vào S0
```

**AC-6: Schema version mismatch**

```
Given payload export có schema_version "1.0", hệ thống đang ở schema "2.0" có migration support
When import
Then migration auto-upgrade payload, import success, response cảnh báo "migrated from 1.0"

Given payload schema_version "0.5" (legacy không support)
When import
Then 400 "SCHEMA_VERSION_UNSUPPORTED"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm bulk export nhiều scenario qua ZIP — lộ trình.
- KHÔNG bao gồm publish-to-marketplace từ user (chỉ system admin tạo template).
- KHÔNG bao gồm git integration / version control sync.
- KHÔNG bao gồm UI browser template — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `ScenarioSerializer` (export sang YAML/JSON + scrub fields).
- [ ] `ScenarioImporter` (parse + validate + commit).
- [ ] Schema migration registry (upgrade payload từ schema cũ sang current).
- [ ] Endpoint clone template.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 3 endpoint mới.
- [ ] Schema YAML chính thức + ví dụ.

**Database / Migration** (`layer:db`)

- [ ] Org `__system` seed.
- [ ] Seed 5-10 template officially-blessed (Fb crawl comments, IG profile fetch, ...) — coordinate với DF-E-08.

**Documentation** (`layer:docs`)

- [ ] How-to "export and share scenario".
- [ ] Template library catalogue.

**Test** (`layer:test`)

- [ ] Round-trip test: export rồi import lại phải tạo scenario equivalent.
- [ ] Negative test schema_version unsupported.
- [ ] Test clone template không affect original.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-005-01 | Positive | Scenario S valid, version 3 | GET /export?format=yaml | 200, payload YAML có metadata + body v3, không lộ organization_id |
| TC-DF-T-04-005-02 | Positive | File YAML hợp lệ | POST /import | 201, scenario mới tạo, validation pass |
| TC-DF-T-04-005-03 | Negative | File YAML body có graph dead-end | POST /import | 400 với danh sách errors; không scenario mới |
| TC-DF-T-04-005-04 | Negative | File YAML có schema_version="0.5" không support | POST /import | 400 "SCHEMA_VERSION_UNSUPPORTED" |
| TC-DF-T-04-005-05 | Edge | Import scenario reference scenario_name không tồn tại, resolve=create_stub | POST /import?resolve=create_stub | 201, S0 tạo + S_dep stub tạo, link đúng |
| TC-DF-T-04-005-06 | Positive | Template T1 trong __system | POST /templates/T1/clone | 201 scenario mới trong org user, T1 không đổi |
| TC-DF-T-04-005-07 | Edge | Round-trip: export S1 sang YAML rồi import lại vào OrgB | Export + Import | Scenario import tương đương S1 (cùng body, cùng kind, cùng config) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-001, DF-T-04-002, DF-T-04-003 (version), DF-T-04-004 (validation).

**Chặn:** DF-E-11 (UI import/export button).

**Phụ thuộc giữa Epic:** Cần seed template phối hợp với DF-E-08 (mẫu Facebook scenario).

**Rủi ro:**

- **Schema export thay đổi phá backward compat:** ràng buộc semver + migration → mọi PR động đến SchemaSerializer phải bump version.
- **YAML parse có vulnerability (vd PyYAML unsafe_load):** dùng safe_load + size limit.
- **Import dependency resolve có thể tạo orphan scenario:** chỉ tạo stub khi user explicit pass flag.

## 10. Điều kiện hoàn thành

- [ ] Code merged, pass CI.
- [ ] Unit test ≥ 80%.
- [ ] Round-trip test export-import pass.
- [ ] Có ≥ 5 template officially-blessed seed vào DB staging.
- [ ] Security: YAML safe parse confirmed, size limit ≤ 1MB.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-02, mục 8 (gợi ý template library).
- **Thuật ngữ:** Scenario, Scenario version.
