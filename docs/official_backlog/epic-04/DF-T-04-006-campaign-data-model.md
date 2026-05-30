# DF-T-04-006 — Campaign data model

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-006 |
| **Title** | Campaign data model & CRUD |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P0 |
| **Story Points** | 3 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-04-01 |
| **Truy vết — UC refs** | UC-04-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Campaign là **đơn vị vận hành** của Social Data Operator — họ nói "chạy campaign Friday-Comments" chứ không nói "chạy scenario X trên device A,B,C lúc 8h". Đặc tả module FR-04-01 định nghĩa campaign là entity gắn 1 hoặc nhiều scenario với device/device-group đích.

Ticket này tạo entity Campaign cơ bản: schema, CRUD, ownership theo organization, ràng buộc khi xoá. Lifecycle FSM tách riêng ở DF-T-04-007. Binding chi tiết (device, account) tách ở DF-T-04-008/009. Đây là khung; phần thịt vào ngay sau.

P0 vì là tiền đề cho mọi luồng dispatch. SP nhỏ (3) vì pattern tương tự DF-T-04-001.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** tạo campaign với tên, danh sách scenario, danh sách device target, và metadata vận hành
> **Để** có một đơn vị thống nhất để dispatch và theo dõi tiến độ

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp entity `Campaign` với trường: `id`, `organization_id`, `name`, `description`, `status` (chi tiết FSM ở DF-T-04-007, ticket này chỉ persist trường), `created_by`, `created_at`, `updated_at`, `scenario_refs` (array `{scenario_id, scenario_version}`), `tags`, `vars` (JSON campaign vars).
- Hệ thống PHẢI ràng buộc ownership theo organization; cross-org isolation như scenario.
- Hệ thống PHẢI từ chối tạo campaign tên trùng trong cùng org.
- Hệ thống PHẢI cho phép campaign tham chiếu nhiều scenario (FR-04-01: "một hoặc nhiều scenario").
- Hệ thống PHẢI cho phép pin scenario_version cụ thể (mặc định = current_version lúc tạo); sau đó update scenario không ảnh hưởng campaign trừ khi user explicit re-pin.
- Hệ thống PHẢI từ chối xoá campaign đang ở status `running`.
- Hệ thống PHẢI cho phép soft delete (status archived).
- Hệ thống PHẢI emit domain event `campaign.created`, `campaign.updated`, `campaign.archived`.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo campaign — luồng thành công**

```
Given user OrgA có quyền campaign.create
And scenario S1, S2 tồn tại trong OrgA với current_version=3 và 1
When POST /campaigns body { name: "FridayCrawl", scenario_refs: [{scenario_id: S1}, {scenario_id: S2}], vars: {kw:"news"} }
Then 201, campaign_id mới, scenario_refs lưu với pinned version [{S1, 3}, {S2, 1}]
And status = "draft", domain event campaign.created phát
```

**AC-2: Pin version explicit**

```
Given user POST campaign với scenario_refs: [{scenario_id: S1, scenario_version: 2}]
And S1 hiện tại current_version=3 nhưng version 2 tồn tại
Then campaign lưu pinned version 2
```

**AC-3: Cross-org reference reject**

```
Given user OrgA tạo campaign tham chiếu scenario thuộc OrgB
When POST /campaigns
Then 400 "SCENARIO_NOT_FOUND" (không leak existence)
```

**AC-4: Không xoá campaign running**

```
Given campaign C status="running"
When DELETE /campaigns/C
Then 409 "CAMPAIGN_RUNNING" với hướng dẫn "cancel trước khi delete"
And C giữ status
```

**AC-5: Pin version không tồn tại**

```
Given user POST campaign với scenario_refs: [{scenario_id: S1, scenario_version: 99}] (99 không tồn tại)
When POST
Then 400 "SCENARIO_VERSION_NOT_FOUND"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm FSM lifecycle (chỉ persist field `status`) — DF-T-04-007.
- KHÔNG bao gồm device binding chi tiết — DF-T-04-008.
- KHÔNG bao gồm account binding — DF-T-04-009.
- KHÔNG bao gồm dispatch logic — DF-T-04-010.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `Campaign` entity + repository.
- [ ] Service layer cho CRUD + duplicate name check.
- [ ] Scenario reference resolver (validate exist + pin version).
- [ ] Domain event publisher.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI 5 endpoint CRUD.
- [ ] Mã lỗi: `CAMPAIGN_NAME_DUPLICATE`, `CAMPAIGN_NOT_FOUND`, `CAMPAIGN_RUNNING`, `SCENARIO_VERSION_NOT_FOUND`.

**Database / Migration** (`layer:db`)

- [ ] Bảng `campaigns` với index (org_id, name_lower) partial unique on deleted_at IS NULL.
- [ ] Bảng `campaign_scenario_refs` (campaign_id, scenario_id, scenario_version, order_index).
- [ ] Cột `vars` JSONB.

**Documentation** (`layer:docs`)

- [ ] Update `docs/modules/campaigns.md` Campaign entity.

**Test** (`layer:test`)

- [ ] Unit + integration CRUD + cross-org isolation.
- [ ] Test pin version.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-006-01 | Positive | OrgA có S1, S2 | POST campaign 2 scenarios không pin | 201, campaign tạo, pinned ở current_version từng scenario |
| TC-DF-T-04-006-02 | Positive | S1 có version 2 và 3 | POST campaign với scenario_version=2 | 201, pinned đúng v2 |
| TC-DF-T-04-006-03 | Negative | Campaign tên "X" đã có trong OrgA | POST campaign "x" (case-insensitive) | 409 "CAMPAIGN_NAME_DUPLICATE" |
| TC-DF-T-04-006-04 | Negative | Scenario S99 không tồn tại | POST campaign ref S99 | 400 "SCENARIO_NOT_FOUND" |
| TC-DF-T-04-006-05 | Edge | Campaign C đang running | DELETE C | 409 "CAMPAIGN_RUNNING" |
| TC-DF-T-04-006-06 | Edge | OrgB scenario S2 | OrgA POST campaign ref S2 | 400 "SCENARIO_NOT_FOUND" (không leak) |
| TC-DF-T-04-006-07 | Positive | Campaign C "draft" | PATCH vars | 200, vars cập nhật, version không change (campaign không version) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-001, DF-T-04-003 (versioning).

**Chặn:** DF-T-04-007, DF-T-04-008, DF-T-04-009, DF-T-04-010.

**Phụ thuộc giữa Epic:** DF-E-01 (RBAC, org).

**Rủi ro:**

- **Pin version không cập nhật tự động:** intended behavior; doc cần làm rõ "campaign giữ scenario version đã pin cho đến khi user explicit re-pin".
- **Race condition tạo trùng tên:** unique index DB.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Test case mapped.
- [ ] Doc updated.
- [ ] Telemetry: campaign.created/archived metric.
- [ ] Code review ≥ 1.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-01.
- **Thuật ngữ:** Campaign.
- **Nhóm người dùng:** Social Data Operator.
