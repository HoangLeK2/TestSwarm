# DF-T-10-010 — Tool registry / discovery (`tools/list` Preview channel)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-010 |
| **Title** | Tool registry + discovery — `tools/list` Preview channel, tool deprecation flags |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:contract`, `type:feature`, `persona:ai-ops`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-10-01, FR-10-02 |
| **Truy vết — UC refs** | UC-10-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Contract DF-E-10 ở trạng thái Preview, đồng nghĩa các tool có thể được thêm / sửa / thu hồi. Agent đăng ký lần đầu cần một cơ chế discovery rõ ràng: tool nào đang Preview, tool nào đã deprecated, tool nào còn experimental sâu hơn (chưa stable trong Preview). Ticket này nâng cấp `tools/list` của DF-T-10-001 thành discovery có channel + deprecation flag.

Persona: **Automation Builder** đọc tools/list trước khi viết prompt; **AI Operations Supervisor** dùng để cấp token đúng scope.

> **Cảnh báo Preview:** Đây là entry point thông báo trạng thái Preview tới agent. Mỗi response tools/list PHẢI có cảnh báo Preview rõ ràng (top-level + per-tool).

Ưu tiên P2.

## 3. Câu chuyện người dùng

> **Là** Automation Builder dựng prompt agent
> **Tôi muốn** đọc `tools/list` để biết tool nào đang Preview, tool nào deprecated, tool nào sẽ remove trong release tới
> **Để** prompt agent không phụ thuộc tool sắp bị bỏ và tôi có kế hoạch migration sớm.

## 4. Yêu cầu chức năng

- `tools/list` PHẢI bao gồm field top-level `server_status = "preview"` và `contract_version` — trace FR-10-01.
- Mỗi tool PHẢI có `preview = true|false`, `stability = "experimental" | "preview" | "stable"`, `deprecated = false|true`, `deprecated_since` (nếu có), `removed_in` (nếu đã lên kế hoạch) — trace FR-10-02.
- Mỗi tool PHẢI có `description` kèm cảnh báo Preview rõ ràng — trace FR-10-02.
- Discovery PHẢI hỗ trợ filter `include_deprecated = false` (mặc định) — trace FR-10-02.
- Discovery PHẢI tôn trọng scope token: chỉ trả tool mà token được phép gọi — trace FR-10-04, FR-10-05.
- NÊN có field `recommended_alternative` cho tool deprecated.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: tools/list response có cảnh báo Preview**

```
Given MCP server đang chạy với registry tải xong
When agent gọi tools/list
Then response có server_status="preview", contract_version="1.x"
And mỗi tool có field preview, stability, deprecated, description chứa cảnh báo Preview
```

**AC-2: Filter scope theo token**

```
Given agent dùng DEVICE_FARM_MCP_TOKEN
When agent gọi tools/list
Then response chỉ trả tool có token_scope chứa "device" hoặc "both"
And không trả tool campaign / content / scenario
```

**AC-3: Deprecated tool**

```
Given tool df_old_foo có deprecated=true, deprecated_since="2026-Q3"
When agent gọi tools/list (mặc định include_deprecated=false)
Then df_old_foo không xuất hiện
When agent gọi tools/list(include_deprecated=true)
Then df_old_foo xuất hiện với recommended_alternative="df_new_foo"
```

**AC-4: contract_version bump khi thay đổi schema**

```
Given release N có contract_version "1.2"
When release N+1 thay đổi schema input của 1 tool
Then contract_version response trả về "1.3" hoặc "2.0" theo SemVer
And changelog có entry rõ
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm dynamic tool registration runtime — registry static từ file.
- KHÔNG bao gồm UI hiển thị discovery — Preview banner UI DF-T-10-014 đề cập.
- KHÔNG bao gồm metering tool usage theo agent — quota DF-T-10-012.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Mở rộng response tools/list với field stability + deprecation.
- [ ] Filter theo scope token.
- [ ] Lấy contract_version từ build metadata.

**Contract / API** (`layer:contract`)

- [ ] Schema response tools/list mở rộng.
- [ ] Quy ước SemVer bump version.

**Documentation** (`layer:docs`)

- [ ] Doc discovery semantics.
- [ ] Doc deprecation policy (cảnh báo trước ≥ 1 release trước khi remove).

**Test** (`layer:test`)

- [ ] Test response shape.
- [ ] Test scope filter.
- [ ] Test deprecated flag.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-010-01 | Positive | Registry hợp lệ | tools/list | Có server_status preview + contract_version + per-tool flag |
| TC-DF-T-10-010-02 | Positive | Token device-scoped | tools/list | Chỉ tool device-level |
| TC-DF-T-10-010-03 | Negative | Token revoked | tools/list | df.unauthorized |
| TC-DF-T-10-010-04 | Positive | Tool deprecated | tools/list(include_deprecated=true) | Tool xuất hiện kèm recommended_alternative |
| TC-DF-T-10-010-05 | Edge | Registry trống | tools/list | Empty array tools + server_status preview + warning rõ "no tools registered" |
| TC-DF-T-10-010-06 | Negative | contract_version cũ không bump khi schema đổi | CI check | CI fail với hint "bump contract_version" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-001, DF-T-10-002.

**Chặn:** DF-T-10-014 (banner đọc discovery để hiển thị contract_version).

**Phụ thuộc giữa Epic:** Không trực tiếp.

**Rủi ro:**

- **Agent không đọc deprecation flag và tiếp tục dùng tool cũ:** doc khuyến nghị + supervisor monitoring.
- **contract_version bump sai gây mismatch integrator:** policy SemVer rõ; CI check thay đổi schema → require bump.

**Phụ thuộc bên ngoài:** MCP protocol spec.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter tools_list_calls per agent.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes Preview + ghi rõ contract_version.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md FR-10-01, FR-10-02](../../official_docs/modules/10-mcp-agent-tools.md).
- **Nhóm người dùng:** Automation Builder, AI Operations Supervisor (Preview).
- **Thuật ngữ:** df_* tool, MCP server.
