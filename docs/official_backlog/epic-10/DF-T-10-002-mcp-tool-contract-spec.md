# DF-T-10-002 — Đặc tả contract `df_*` tool family

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-002 |
| **Title** | Đặc tả contract `df_*` tool family — schema, naming, parity với HTTP route |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:contract`, `layer:docs`, `type:feature`, `persona:ai-ops`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-10-02, FR-10-03, FR-10-08, FR-10-10 |
| **Truy vết — UC refs** | UC-10-03, UC-10-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

MCP server bootstrap (DF-T-10-001) cho phép agent đăng ký, nhưng chưa nói "agent gọi tool gì, schema thế nào, có hành vi nào tương đương HTTP route nào". Nếu mỗi developer tự đặt tên tool và schema khác nhau, contract DF-E-10 sẽ vỡ — agent đoán nhầm tool, parity HTTP/MCP lệch, audit không truy vết được. Ticket này định nghĩa **contract chuẩn** của toàn bộ `df_*` tool family: naming convention, schema in/out, mapping sang HTTP route, khung guardrail platform.

Persona chính là **AI Operations Supervisor (Preview)** — họ cần một contract ổn định để cấu hình prompt agent. Persona phụ là **Platform Engineer** — họ là người thực thi contract khi thêm tool mới. Vị trí trong luồng: nền tảng tham chiếu cho mọi ticket tool sau (DF-T-10-004 → DF-T-10-009).

> **Cảnh báo Preview:** Contract này thuộc phần mở rộng đang được nghiên cứu, **KHÔNG thuộc năng lực cốt lõi** của Device Farm. Có thể bị thu hồi hoặc thay đổi giữa các release. Agent bên ngoài tiêu thụ contract này phải hiểu rủi ro thay đổi giữa các phiên bản.

Ưu tiên P1 vì mọi ticket tool sau đứng trên contract này.

## 3. Câu chuyện người dùng

> **Là** Automation Builder (đang dựng prompt agent)
> **Tôi muốn** đọc một contract duy nhất mô tả tất cả `df_*` tool — tên, input shape, output shape, HTTP route tương ứng, guardrail platform
> **Để** prompt cho agent không phải đoán schema và có thể audit cross-reference với surface người vận hành.

Persona phụ: AI Operations Supervisor review contract trước khi cấp token; Platform Engineer dùng contract như checklist khi thêm tool mới.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có một tài liệu / file YAML/JSON là single source of truth cho tool registry, định danh từng tool theo prefix `df_` — trace FR-10-02.
- Mỗi tool PHẢI khai báo: `name`, `description` (kèm warning Preview), `input_schema` (JSON Schema), `output_schema`, `http_route_ref` (route HTTP wrap), `token_scope` (device-scoped / user-scoped / both), `family` (session / gesture / hierarchy / scenario / campaign / content / account / discovery) — trace FR-10-02, FR-10-04, FR-10-05, FR-10-08.
- Mỗi tool device-level PHẢI chấp nhận tham số định danh dạng `device_serial` HOẶC `session_id` — trace FR-10-03.
- Khi cả `device_serial` lẫn `session_id` đều thiếu, tool PHẢI trả error contract chuẩn `df.invalid_argument` — trace FR-10-03 + DF-T-10-013.
- Contract PHẢI khai báo khung guardrail platform cho tool có ảnh hưởng nghiệp vụ (allowed action, evidence requirement, handoff condition) — trace FR-10-10.
- Contract PHẢI ràng buộc parity: mỗi tool wrap chính xác một HTTP route đã có; thêm tool không có route tương ứng bị reject ở review — trace FR-10-08.
- Hệ thống NÊN expose contract qua `tools/list` ở format MCP chuẩn — trace FR-10-02.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Contract file tồn tại và parsable**

```
Given repo có file tool registry `mcp/tool_registry.yaml`
When build pipeline parse registry
Then 100% tool có đủ field bắt buộc (name, description, input_schema, output_schema, http_route_ref, token_scope, family)
And mỗi tool name match regex ^df_[a-z_]+$
And không tool nào trùng tên
```

**AC-2: Tool device-level chấp nhận device_serial hoặc session_id**

```
Given tool df_get_session_info đã đăng ký với schema chuẩn
When agent gọi tool với device_serial="A12345"
Then tool dispatch OK
When agent gọi tool với session_id="sess-abc"
Then tool dispatch OK
When agent gọi tool với cả hai field rỗng
Then tool trả mã lỗi "df.invalid_argument" với message rõ ràng
```

**AC-3: Tool campaign / content / scenario yêu cầu MCP_AUTH_TOKEN**

```
Given contract khai báo tool df_campaign_create có token_scope = ["user"]
And agent đang dùng DEVICE_FARM_MCP_TOKEN (device-scoped)
When agent gọi df_campaign_create
Then tool trả error "df.permission_denied"
And error message dẫn link tới tài liệu token scope
```

**AC-4: Parity HTTP route — không tool mồ côi**

```
Given có tool df_foo trong registry mà không có http_route_ref hoặc route_ref trỏ tới route không tồn tại
When CI parity check chạy
Then build fail với message "Tool df_foo missing HTTP route parity"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm implementation tool cụ thể — thuộc DF-T-10-004 → DF-T-10-009.
- KHÔNG bao gồm authentication logic — thuộc DF-T-10-003.
- KHÔNG bao gồm guardrail platform-specific cho từng platform — thuộc DF-E-08 (Social Platform Extensions).
- KHÔNG bao gồm error message catalog đầy đủ — thuộc DF-T-10-013.
- KHÔNG bao gồm dynamic registry override ở runtime — registry là static file.

## 7. Kế hoạch triển khai

**Contract / API** (`layer:contract`)

- [ ] Tạo file `mcp/tool_registry.yaml` với schema rõ ràng.
- [ ] Định nghĩa JSON Schema cho input/output mỗi tool family (gesture, hierarchy, session, scenario, campaign, content, account).
- [ ] Định nghĩa khung guardrail trong contract: `allowed_action`, `evidence_required`, `handoff_condition`.
- [ ] Mapping tool ↔ http_route_ref với link tới OpenAPI operation id.

**Backend** (`layer:backend`)

- [ ] Loader đọc registry, validate schema khi MCP server start.
- [ ] Hook đăng ký tool vào tools/list response.
- [ ] CI parity check (script so contract với OpenAPI để bắt tool mồ côi).

**Documentation** (`layer:docs`)

- [ ] Bổ sung `docs/modules/10-mcp-agent-tools.md` mục "Tool contract spec".
- [ ] Mỗi tool có warning Preview rõ trong description.
- [ ] Changelog ghi rõ contract version.

**Test** (`layer:test`)

- [ ] Test unit cho loader (file thiếu field bị reject).
- [ ] Test parity script (tool không có route → fail).
- [ ] Test integration: tools/list trả về đúng entries từ registry.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-002-01 | Positive | Registry hợp lệ với 10 tool | Start MCP server → tools/list | 10 entry trả về đúng schema |
| TC-DF-T-10-002-02 | Positive | Tool df_get_session_info trong registry chấp nhận cả device_serial và session_id | Gọi với session_id | Dispatch OK |
| TC-DF-T-10-002-03 | Negative | Tool df_foo trong registry không có http_route_ref | Run CI parity check | Build fail với message rõ "Tool df_foo missing HTTP route parity" |
| TC-DF-T-10-002-04 | Negative | Tool df_campaign_create có token_scope user, agent dùng device-scoped token | Gọi tool | Error df.permission_denied |
| TC-DF-T-10-002-05 | Edge | Registry có 2 tool trùng tên df_tap | Start server | Server fail start với lỗi duplicate tool name |
| TC-DF-T-10-002-06 | Edge | Tool có input_schema không hợp lệ JSON Schema | Start server | Loader reject schema, fail start với lỗi rõ |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-001 (cần MCP server scaffold để load registry).

**Chặn:** DF-T-10-003 → DF-T-10-013 (tất cả ticket tool và auth đứng trên contract này).

**Phụ thuộc giữa Epic:**

- DF-E-02, DF-E-04, DF-E-06, DF-E-07 — phải có OpenAPI operation id ổn định để route_ref trỏ tới.
- DF-E-08 — khung guardrail tham chiếu nội dung platform khai báo ở DF-E-08.

**Rủi ro:**

- **Contract drift:** thêm tool nhưng quên update OpenAPI → CI parity check là rào chắn.
- **Schema quá rộng làm agent dễ misuse:** giữ schema sát thật, không cho free-form params.
- **Preview thay đổi gây breaking cho integrator:** mọi thay đổi contract bump version + ghi rõ changelog.

**Phụ thuộc bên ngoài:** JSON Schema draft 2020-12, MCP tool spec.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI parity check.
- [ ] Test case TC-DF-T-10-002-* được map sang test tự động.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật contract spec.
- [ ] Mọi tool trong registry đều có warning Preview trong description.
- [ ] Code review có ≥ 1 approve từ owner module + Platform Engineer.
- [ ] Release notes ghi version contract Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md §6 FR-10-02, FR-10-03, FR-10-08, FR-10-10](../../official_docs/modules/10-mcp-agent-tools.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview), Platform Engineer.
- **Thuật ngữ:** df_* tool, Guardrail, MCP session.
- **Lộ trình:** [99-roadmap-and-faq.md §4.3](../../official_docs/99-roadmap-and-faq.md).
