# DF-T-10-006 — Tool `df_campaign_create` — agent tạo campaign

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-006 |
| **Title** | Tool `df_campaign_create` — agent tạo campaign mới từ scenario có sẵn |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:contract`, `type:feature`, `persona:ai-ops`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-10-02, FR-10-05, FR-10-08, FR-10-18 |
| **Truy vết — UC refs** | UC-10-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Một số use case AI agent vượt ra ngoài "thao tác 1 device" — agent cần tạo campaign chạy scenario trên một nhóm device. Tool `df_campaign_create` cho phép agent tạo bản ghi campaign (chưa dispatch — dispatch là tool DF-T-10-007). Tách create / run thành 2 tool để supervisor có thể review trước khi run (kỷ luật evidence cho action L3).

Persona chính là **AI Operations Supervisor (Preview)** review campaign agent đề xuất; persona phụ là **Automation Builder** dùng tool để prototype scenario thông qua agent.

> **Cảnh báo Preview:** Tool này có khả năng tạo tài nguyên thực trong tổ chức (campaign), thuộc phần mở rộng nghiên cứu. Khuyến nghị cấp MCP_AUTH_TOKEN cho service account scope hẹp, không cấp token admin.

Ưu tiên P2 — không phải foundation nhưng là demo capability quan trọng để chứng minh contract Preview hoạt động.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** agent gọi `df_campaign_create(scenario_id, device_group_id, runtime_vars)` để tạo bản nháp campaign chờ tôi review
> **Để** tôi vẫn giữ quyền chốt run / không run thay vì agent tự ý dispatch.

## 4. Yêu cầu chức năng

- Tool PHẢI yêu cầu MCP_AUTH_TOKEN (user-scoped) — trace FR-10-05.
- Tool PHẢI wrap đúng route campaign-create DF-E-04 — trace FR-10-08.
- Tool PHẢI nhận tham số: `scenario_id` (bắt buộc), `device_group_id` HOẶC `device_serials[]`, `runtime_vars` (object), `name` (optional) — trace FR-10-02, FR-10-18.
- Campaign tạo qua tool PHẢI có flag `created_via = "mcp_agent"` để truy vết — trace FR-10-09.
- Campaign tạo qua tool PHẢI ở trạng thái `draft` (chưa run) — yêu cầu nghiệp vụ để supervisor review.
- Tool PHẢI validate scenario thuộc org của token và device thuộc org — trace FR-10-05, FR-10-20.
- Tool PHẢI ghi audit log với input đầy đủ (scenario_id, device list, runtime_vars) — trace FR-10-09 + DF-T-10-011.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo campaign draft thành công**

```
Given scenario S1 và device group G1 thuộc org X
And agent dùng MCP_AUTH_TOKEN của user thuộc org X
When agent gọi df_campaign_create(scenario_id=S1, device_group_id=G1)
Then trả về campaign_id ở trạng thái draft
And campaign metadata có created_via="mcp_agent"
And audit log ghi input đầy đủ
```

**AC-2: Token device-scoped bị reject**

```
Given agent dùng DEVICE_FARM_MCP_TOKEN
When agent gọi df_campaign_create
Then df.permission_denied "user-scoped token required"
```

**AC-3: Cross-org bị chặn**

```
Given scenario S1 thuộc org Y; token thuộc org X
When agent gọi df_campaign_create(scenario_id=S1, ...)
Then df.permission_denied + audit log cross-org
And không sinh campaign
```

**AC-4: Validate runtime_vars**

```
Given scenario S1 yêu cầu runtime_vars có field "target_url"
When agent gọi df_campaign_create thiếu target_url
Then df.invalid_argument với message liệt kê field thiếu
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm dispatch / run — DF-T-10-007.
- KHÔNG bao gồm chỉnh sửa scenario — agent không thể edit scenario qua MCP.
- KHÔNG bao gồm tạo device group mới — DF-E-02.
- KHÔNG bao gồm schedule campaign — DF-E-05.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Handler df_campaign_create wrap service campaign-create.
- [ ] Force created_via="mcp_agent" + status="draft".
- [ ] Validate ownership scenario / device.
- [ ] Audit log.

**Contract / API** (`layer:contract`)

- [ ] Registry entry với schema input/output.
- [ ] http_route_ref tới OpenAPI campaign-create.

**Documentation** (`layer:docs`)

- [ ] Doc + warning Preview.

**Test** (`layer:test`)

- [ ] Unit + integration test.
- [ ] Cross-org test.
- [ ] runtime_vars validation test.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-006-01 | Positive | Scenario, group cùng org, token user-scoped | Gọi df_campaign_create | campaign_id draft, audit log |
| TC-DF-T-10-006-02 | Positive | Truyền device_serials thay vì group | Gọi tool | Tạo OK với danh sách device serial |
| TC-DF-T-10-006-03 | Negative | Token device-scoped | Gọi tool | df.permission_denied |
| TC-DF-T-10-006-04 | Negative | scenario_id thuộc org khác | Gọi tool | df.permission_denied + audit cross-org |
| TC-DF-T-10-006-05 | Edge | runtime_vars có 100 KB JSON | Gọi tool | OK nếu < limit (mặc định 256 KB), > limit thì df.invalid_argument |
| TC-DF-T-10-006-06 | Negative | scenario_id không tồn tại | Gọi tool | df.not_found |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-002, DF-T-10-003, DF-T-10-005.

**Chặn:** DF-T-10-007.

**Phụ thuộc giữa Epic:** **DF-E-04** (Campaign module) — route create.

**Rủi ro:**

- **Agent tạo hàng loạt campaign draft gây rác:** rate-limit DF-T-10-012 + quota soft trên campaign draft.
- **Agent set runtime_vars sai gây campaign hỏng sau khi run:** validation theo scenario schema.

**Phụ thuộc bên ngoài:** Service campaign DF-E-04.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter campaign_created_via_mcp.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md FR-10-18](../../official_docs/modules/10-mcp-agent-tools.md).
- **Module liên quan:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview).
- **Thuật ngữ:** Campaign, Scenario, MCP session.
