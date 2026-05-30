# DF-T-04-001 — Scenario data model & persistence

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-001 |
| **Title** | Scenario data model & persistence (entity + repository) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-04-02, FR-04-03, FR-04-04 |
| **Truy vết — UC refs** | UC-04-01, UC-04-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Hiện tại team chưa có một model thống nhất để lưu "việc cần làm trên thiết bị". Mỗi script python rời rạc, mỗi nhóm sửa file YAML theo phong cách riêng. Khi cần audit "scenario X version nào đang chạy trên campaign Y", không có cách trả lời. Ticket này thiết lập **entity Scenario** ở backend — schema cơ sở dữ liệu, repository, và API CRUD tối thiểu để các ticket sau có chỗ persist scenario graph.

Persona hưởng lợi là **Automation Builder**, người mỗi ngày tạo và bảo trì scenario. Khi scenario có entity ổn định với id duy nhất, owner_org, scenario_version, và metadata cơ bản, mọi flow downstream (versioning, validation, import/export, execution) đều có một điểm tham chiếu. Ticket này nằm ở đầu chuỗi của DF-E-04 — không thể có DSL, campaign, hay execution nếu chưa có scenario.

Mức ưu tiên P0: mọi ticket khác trong DF-E-04 (trừ data model campaign) đều bị chặn bởi ticket này. Lộ trình đặt scenario là Active capability từ ngày đầu (xem mục 7 đặc tả module).

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** lưu scenario của tôi vào hệ thống với id duy nhất, có thể truy vấn và tham chiếu lại
> **Để** dùng cùng một scenario cho nhiều campaign khác nhau và team có thể audit phiên bản nào đang chạy

Persona phụ: Social Data Operator (consume scenario qua API list/search).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp entity `Scenario` với các trường tối thiểu: `id`, `organization_id`, `name`, `description`, `kind` (`sequence` | `graph`), `status` (`draft` | `active` | `archived`), `created_by`, `created_at`, `updated_at`, `scenario_version`, `body_json` (placeholder cho DSL, hoàn chỉnh ở DF-T-04-002) — trace FR-04-02.
- Hệ thống PHẢI ràng buộc ownership: scenario thuộc về một organization duy nhất; user của org khác không truy cập được (trừ super-admin) — trace FR-04-01 (carry-over).
- Hệ thống PHẢI cung cấp API CRUD: `POST /scenarios`, `GET /scenarios/{id}`, `GET /scenarios?org=...`, `PATCH /scenarios/{id}`, `DELETE /scenarios/{id}` (soft delete, chuyển status `archived`) — trace FR-04-02.
- Hệ thống PHẢI từ chối tạo scenario có tên trùng trong cùng org (case-insensitive) — trace FR-04-02.
- Hệ thống PHẢI lưu `scenario_version` tăng đơn điệu khi scenario được sửa nội dung (chi tiết policy versioning ở DF-T-04-003, ticket này chỉ chuẩn bị trường).
- Hệ thống PHẢI từ chối xóa scenario đang được tham chiếu bởi campaign `active` hoặc `running` — trace FR-04-01.
- Hệ thống PHẢI emit domain event `scenario.created` / `scenario.updated` / `scenario.archived` để các module khác (Notifications, Analytics) subscribe.
- Hệ thống NÊN hỗ trợ tag/label tự do trên scenario để Automation Builder phân loại theo platform / use case.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo scenario mới — luồng thành công**

```
Given user thuộc organization "OrgA" và có quyền scenario.create
And chưa có scenario nào tên "FB-CrawlComments" trong OrgA
When user gọi POST /scenarios với body { name: "FB-CrawlComments", kind: "sequence", description: "..." }
Then hệ thống trả về 201 với id duy nhất (UUID), scenario_version = 1, status = "draft"
And domain event scenario.created được phát với scenario_id và organization_id = OrgA
```

**AC-2: Không cho tạo trùng tên trong cùng org**

```
Given OrgA đã có scenario tên "FB-CrawlComments"
When user của OrgA gọi POST /scenarios với name = "fb-crawlcomments" (khác case)
Then hệ thống trả về 409 Conflict với code "SCENARIO_NAME_DUPLICATE"
And không có scenario mới được tạo
```

**AC-3: Xóa scenario đang được tham chiếu**

```
Given scenario S1 đang được tham chiếu bởi campaign C1 ở trạng thái "running"
When admin gọi DELETE /scenarios/S1
Then hệ thống trả về 409 Conflict với code "SCENARIO_IN_USE"
And response chứa danh sách campaign đang dùng (C1)
And scenario S1 không đổi status
```

**AC-4: Cross-org isolation**

```
Given scenario S1 thuộc OrgA
When user của OrgB gọi GET /scenarios/S1
Then hệ thống trả về 404 Not Found (không leak existence)
And không có audit log nào ghi "OrgB đọc scenario của OrgA"
```

**AC-5: Soft delete**

```
Given scenario S2 thuộc OrgA, không campaign nào tham chiếu
When user gọi DELETE /scenarios/S2
Then status chuyển thành "archived"
And GET /scenarios/S2 vẫn trả về 200 với status="archived"
And GET /scenarios?org=OrgA (default filter) không trả S2 trừ khi pass param include_archived=true
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm DSL chi tiết của body_json — xử lý ở DF-T-04-002.
- KHÔNG bao gồm versioning policy (immutable revision, diff) — xử lý ở DF-T-04-003.
- KHÔNG bao gồm validation pipeline (schema, depth check, lint) — xử lý ở DF-T-04-004.
- KHÔNG bao gồm import/export YAML — xử lý ở DF-T-04-005.
- KHÔNG bao gồm UI editor — thuộc DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Tạo struct/class `Scenario` với các trường nêu ở FR.
- [ ] Tạo `ScenarioRepository` với method `create`, `findById`, `findByOrg`, `update`, `softDelete`.
- [ ] Implement quy tắc nghiệp vụ "duplicate name in org" trong service layer.
- [ ] Implement check "in use by active/running campaign" trước khi delete (gọi campaign repo, sẽ cần stub đến khi DF-T-04-006 xong).
- [ ] Wire domain event publisher (reuse event bus của DF-E-01).

**Contract / API** (`layer:contract`)

- [ ] Thêm OpenAPI spec cho 5 endpoint CRUD.
- [ ] Định nghĩa mã lỗi chuẩn: `SCENARIO_NAME_DUPLICATE`, `SCENARIO_IN_USE`, `SCENARIO_NOT_FOUND`, `SCENARIO_FORBIDDEN`.
- [ ] Định nghĩa schema response Scenario (không bao gồm body_json full khi list, có khi get).

**Database / Migration** (`layer:db`)

- [ ] Migration tạo bảng `scenarios` với index trên (organization_id, name_lower), (organization_id, status).
- [ ] Cột `body_json` kiểu JSONB (Postgres) / JSON (khác), nullable cho phép create rỗng rồi update body sau.
- [ ] Migration tạo bảng `scenario_tags` (many-to-many).
- [ ] Cột `deleted_at` để soft delete; query mặc định filter `deleted_at IS NULL AND status != 'archived'`.

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/modules/campaigns.md` mục Scenario entity.
- [ ] Ghi changelog entry "Scenario entity GA".

**Test** (`layer:test`)

- [ ] Unit test repository (in-memory hoặc test container).
- [ ] Unit test service layer cho 5 AC.
- [ ] Integration test API CRUD + cross-org isolation.
- [ ] Test domain event được phát đúng.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-001-01 | Positive | User OrgA có quyền `scenario.create`, chưa có scenario nào tên "S1" | Tạo scenario name="S1", kind="sequence" | 201, response.id là UUID hợp lệ, response.scenario_version=1, response.status="draft", domain event `scenario.created` được publish |
| TC-DF-T-04-001-02 | Positive | OrgA có scenario S1 status "active", không campaign tham chiếu | DELETE /scenarios/S1 | 200, status chuyển "archived", domain event `scenario.archived` phát, GET vẫn trả S1 status="archived" |
| TC-DF-T-04-001-03 | Negative | OrgA đã có scenario tên "FB-Crawl" | POST /scenarios name="fb-crawl" (khác case) | 409 với mã lỗi "SCENARIO_NAME_DUPLICATE", không scenario mới được tạo, không event publish |
| TC-DF-T-04-001-04 | Negative | Scenario S2 thuộc OrgA đang được campaign C1 ở "running" tham chiếu | DELETE /scenarios/S2 | 409 với code "SCENARIO_IN_USE", response chứa array `referenced_by: [C1]`, S2 không đổi status |
| TC-DF-T-04-001-05 | Edge | Scenario S1 thuộc OrgA, user thuộc OrgB không có super-admin role | GET /scenarios/S1 | 404 Not Found, không 403 (không leak existence), audit log không ghi violation |
| TC-DF-T-04-001-06 | Edge | Tạo 100 scenario song song với cùng name "Test" trong cùng OrgA (race condition) | Concurrent POST x100 | Đúng 1 scenario được tạo (201), 99 còn lại nhận 409 — không có 2 record cùng name trong DB |
| TC-DF-T-04-001-07 | Negative | User không có quyền `scenario.create` | POST /scenarios | 403 Forbidden với code "PERMISSION_DENIED" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-E-01 phải có RBAC + organization model (DF-E-01).

**Chặn:** DF-T-04-002, DF-T-04-003, DF-T-04-004, DF-T-04-005, DF-T-04-006, DF-T-04-010.

**Phụ thuộc giữa Epic:** DF-E-01 (RBAC, organization). Sau khi xong, DF-E-11 cần entity này cho UI list scenario.

**Rủi ro:**

- **Race condition khi tạo trùng tên đồng thời:** có thể tạo 2 scenario cùng name nếu không unique constraint → dùng DB unique index trên (organization_id, lower(name)).
- **Soft delete + hard delete xung đột:** archive scenario rồi tạo lại tên đó sẽ conflict nếu unique index không filter `deleted_at` → unique index nên partial: `WHERE deleted_at IS NULL`.
- **body_json kích thước lớn:** scenario phức tạp có thể lên hàng trăm KB → giới hạn body_json ≤ 1MB ở API gateway level.

**Phụ thuộc bên ngoài:** PostgreSQL JSONB hoặc tương đương; event bus của DF-E-01.

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage ≥ 80% trên file thay đổi.
- [ ] Tất cả test case TC-DF-T-04-001-* được map sang test tự động.
- [ ] Tài liệu kỹ thuật `docs/modules/campaigns.md` cập nhật phần Scenario entity.
- [ ] Tài liệu nghiệp vụ chưa cần update (FR đã đủ).
- [ ] Telemetry: metric `scenario.created.count`, `scenario.archived.count` đã có; log structured cho mọi mutation.
- [ ] Code review ≥ 1 approve từ owner module Campaigns.
- [ ] Release notes update.
- [ ] DB migration đã chạy thử trên staging, rollback script đã test.
- [ ] OpenAPI spec đã được publish lên dev portal.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [docs/official_docs/modules/04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — mục 6, FR-04-02 / FR-04-03 / FR-04-04.
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — ô "Scenario authoring".
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Automation Builder.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Scenario, Scenario version.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — Milestone "Scenario GA".
