# DF-T-04-003 — Scenario versioning & immutability

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-003 |
| **Title** | Scenario versioning & immutable revision history |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:db`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-04-02 (clause scenario_version) |
| **Truy vết — UC refs** | UC-04-01, UC-04-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module FR-04-02 yêu cầu scenario có `scenario_version` để truy vết. Hiện tại team mới có trường int trong entity (DF-T-04-001) nhưng chưa có **policy** rõ ràng: khi nào tăng version, version cũ có còn run được không, campaign đang chạy có bị ảnh hưởng nếu tác giả sửa body không. Đây là vấn đề audit lớn: nếu execution log nói "run scenario S version 3" mà version 3 đã bị overwrite, ta không truy vết được bug.

Ticket này thiết lập **immutable revision model**: mỗi lần body scenario thay đổi đáng kể (semantic change), version mới được snapshot ra một bảng riêng, version cũ vẫn truy vấn được. Campaign / execution bind cụ thể tới `(scenario_id, scenario_version)`. Automation Builder thấy danh sách version, có thể compare và promote một version cũ về "active" nếu version mới có bug.

Persona hưởng lợi chính là Automation Builder (audit và rollback) và Fleet Operator (biết version nào chạy stable). Đây là tiền đề cho feature "diff giữa scenario version" (lộ trình, đặc tả module mục 7) — không làm trong ticket này nhưng schema phải support được.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** mỗi lần sửa scenario nội dung tạo ra một version snapshot immutable, có thể xem lại và promote version cũ về active
> **Để** không mất audit trail và có thể rollback khi version mới có bug

## 4. Yêu cầu chức năng

- Hệ thống PHẢI snapshot body_json mỗi khi PATCH scenario tạo ra **semantic change** (steps thay đổi, edges đổi, error_policy đổi). Trường metadata (name, description, tags) thay đổi KHÔNG bump version.
- Hệ thống PHẢI lưu mỗi version vào bảng `scenario_versions` với `(scenario_id, version_number)` duy nhất, `body_json`, `created_by`, `created_at`, `notes` tùy chọn.
- Hệ thống PHẢI giữ scenario_versions là **immutable** — không UPDATE, không DELETE (hard) sau khi tạo.
- Hệ thống PHẢI cho phép API `GET /scenarios/{id}/versions` trả về danh sách version với metadata cơ bản.
- Hệ thống PHẢI cho phép `GET /scenarios/{id}/versions/{v}` trả về body của version cụ thể.
- Hệ thống PHẢI cho phép `POST /scenarios/{id}/promote` body `{ version: N }` để set version N làm "current active" của scenario.
- Hệ thống PHẢI bind execution tới `(scenario_id, scenario_version)` cụ thể — khi DF-T-04-010 dispatch campaign, snapshot version đang active được record vào execution.
- Hệ thống PHẢI có endpoint `GET /scenarios/{id}/versions/{a}/diff/{b}` (placeholder trả raw JSON diff; UI diff làm sau ở DF-E-11).
- Hệ thống PHẢI cấm xoá scenario version đang được tham chiếu bởi campaign active hoặc execution `running`.
- Hệ thống NÊN cho phép Automation Builder thêm `notes` (release notes) khi promote version mới.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Semantic change bump version**

```
Given scenario S version 1, body có 3 step
When user PATCH /scenarios/S/body thay step 2 (đổi config tap)
Then version 2 được tạo trong scenario_versions với body mới
And scenario.current_version = 2
And version 1 vẫn truy vấn được qua GET /scenarios/S/versions/1
And event scenario.version.created phát với version=2
```

**AC-2: Metadata change KHÔNG bump version**

```
Given scenario S version 1
When user PATCH /scenarios/S đổi description từ "old" sang "new"
Then scenario.current_version vẫn = 1
And không có row mới trong scenario_versions
And event scenario.metadata.updated phát (không phải version.created)
```

**AC-3: Promote version cũ về active**

```
Given scenario S có version 1, 2, 3; current_version = 3
When user POST /scenarios/S/promote body { version: 1, notes: "rollback bug v3" }
Then version 1 trở thành current_active
And version 3 vẫn lưu trong DB (KHÔNG xoá)
And campaign mới tham chiếu scenario S sẽ run version 1
And campaign đang running giữ version đã bind lúc dispatch (không bị đổi runtime)
```

**AC-4: Immutability — không sửa được version cũ**

```
Given version 1 đã được tạo
When admin gọi PUT /scenarios/S/versions/1 (hoặc cố ý chỉnh DB)
Then API trả 405 Method Not Allowed (không có endpoint update)
And ở DB layer, bảng scenario_versions có trigger / constraint chống UPDATE
```

**AC-5: Execution bind version cụ thể**

```
Given campaign C dispatch scenario S khi current_version=2
When DF-T-04-010 tạo execution
Then execution.scenario_id = S, execution.scenario_version = 2
And nếu sau dispatch user promote version 3, execution đang running vẫn chạy version 2
```

**AC-6: Cấm xoá version đang dùng**

```
Given execution running E1 đang dùng (S, version 2)
When admin gọi DELETE /scenarios/S/versions/2
Then 409 code "VERSION_IN_USE" với chi tiết executions referencing
And version 2 không bị xoá
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI diff viewer — DF-E-11.
- KHÔNG bao gồm semantic diff thuật toán (tree diff, structural) — chỉ raw JSON diff; semantic diff là lộ trình.
- KHÔNG bao gồm auto-rollback khi version mới có DLQ rate cao — lộ trình.
- KHÔNG bao gồm branch / fork scenario version — không phải requirement của đặc tả module.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Định nghĩa "semantic change" detector: hash body_json (sort key, omit metadata fields) so sánh với version hiện tại.
- [ ] Wire vào PATCH /scenarios để bump version khi detector trả true.
- [ ] Implement `POST /scenarios/{id}/promote`.
- [ ] Đảm bảo DF-T-04-010 nhận `scenario_version` khi dispatch.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 4 endpoint mới (list versions, get version, promote, diff).
- [ ] Mã lỗi: `VERSION_NOT_FOUND`, `VERSION_IN_USE`, `VERSION_IMMUTABLE`.

**Database / Migration** (`layer:db`)

- [ ] Migration tạo bảng `scenario_versions` (scenario_id, version_number, body_json, created_by, created_at, notes), PK (scenario_id, version_number).
- [ ] Trigger Postgres chống UPDATE / DELETE (hoặc enforce ở app layer + RBAC).
- [ ] Thêm cột `current_version` trên bảng `scenarios`.
- [ ] Backfill: với scenario đã có (từ DF-T-04-001), tạo version 1 từ body hiện tại.

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/modules/campaigns.md` mục "Versioning policy".
- [ ] Viết note "what counts as semantic change" cho Automation Builder.

**Test** (`layer:test`)

- [ ] Unit test detector "semantic change" với 10+ fixture.
- [ ] Integration test promote + rollback.
- [ ] Test immutability: cố update DB trực tiếp → trigger ngăn (nếu dùng DB trigger).
- [ ] Test execution-version binding qua DF-T-04-010 stub.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-003-01 | Positive | Scenario S version 1, body có 3 step | PATCH body đổi config step 2 | Version 2 tạo, current_version=2, version 1 vẫn GET được |
| TC-DF-T-04-003-02 | Positive | Scenario S version 1 | PATCH chỉ đổi description | Không tạo version mới, current_version vẫn 1 |
| TC-DF-T-04-003-03 | Negative | Version 2 đang dùng bởi execution running | DELETE version 2 | 409 "VERSION_IN_USE" với danh sách execution |
| TC-DF-T-04-003-04 | Negative | Version 5 không tồn tại của scenario S | GET /scenarios/S/versions/5 | 404 "VERSION_NOT_FOUND" |
| TC-DF-T-04-003-05 | Edge | Scenario có 100 version | GET /scenarios/S/versions với pagination | Trả về paginated list, mặc định 20/page, có total_count |
| TC-DF-T-04-003-06 | Edge | Promote version 1 trong khi 5 campaign đang running version 3 | POST promote {version:1} | 200, current_version=1, 5 execution running vẫn chạy version 3 đến hết |
| TC-DF-T-04-003-07 | Negative | User không có quyền `scenario.promote` | POST promote | 403 "PERMISSION_DENIED" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-001, DF-T-04-002.

**Chặn:** DF-T-04-005 (import/export cần handle versioning), DF-T-04-010 (execution bind version).

**Phụ thuộc giữa Epic:** Không có cross-epic block trực tiếp; nhưng DF-E-11 sẽ tiêu thụ API list versions cho UI diff viewer.

**Rủi ro:**

- **Hash body để detect semantic change có thể false positive khi key ordering khác:** dùng canonical JSON (sort keys recursively) trước khi hash.
- **Bảng scenario_versions phình to:** không cleanup; giải pháp dài hạn là archive version cũ ra cold storage (không làm trong ticket này) → ghi vào lộ trình.
- **Backfill version 1 cho scenario đang tồn tại:** chạy đồng thời với app traffic có thể race → migration script chạy trong maintenance window.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả test case map sang test tự động.
- [ ] Backfill migration chạy thử trên staging copy của production data và pass.
- [ ] Trigger / constraint immutability đã test (thử direct SQL update).
- [ ] Tài liệu `docs/modules/campaigns.md` cập nhật policy versioning.
- [ ] Telemetry: metric `scenario.version.created.count`, `scenario.version.promoted.count`.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes update.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-02, mục 7 (ma trận năng lực: "Diff giữa scenario version" là lộ trình).
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Scenario version.
- **Nhóm người dùng:** Automation Builder.
