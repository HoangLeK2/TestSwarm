# DF-T-10-013 — Error contract chuẩn `df.*` codes

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-013 |
| **Title** | Error contract chuẩn `df.*` — code catalog, message format, retryable flag |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:contract`, `layer:backend`, `type:feature`, `persona:ai-ops`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-10-02, FR-10-08 |
| **Truy vết — UC refs** | UC-10-03, UC-10-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Agent ra quyết định dựa trên output tool — nếu error message lỗi không có cấu trúc, agent đoán nhầm và retry vô tội vạ hoặc bỏ qua action quan trọng. Mọi ticket DF-E-10 trước đó đã đề cập đến các mã lỗi chuẩn (df.invalid_argument, df.permission_denied, df.conflict, df.precondition_failed, df.unauthorized, df.not_found, df.rate_limited, df.quota_exceeded, df.token_suspended, df.timeout). Ticket này thống nhất chúng thành một **catalog** và quy ước format ổn định.

Persona: **Automation Builder** dựng prompt agent dựa vào mã lỗi; **AI Operations Supervisor** review log dùng cùng catalog.

> **Cảnh báo Preview:** Catalog có thể thêm code mới giữa các release. Cam kết: KHÔNG đổi semantic code đã release; chỉ thêm code mới hoặc deprecate code cũ với cảnh báo.

Ưu tiên P2.

## 3. Câu chuyện người dùng

> **Là** Automation Builder dựng prompt agent
> **Tôi muốn** mỗi error trả về có `code` (`df.*` namespace), `message` con người đọc được, `retryable` flag, `details` object
> **Để** agent biết nên retry hay dừng, biết handoff khi nào, và biết bug ở đâu khi đọc log.

## 4. Yêu cầu chức năng

- Mọi error response từ tool PHẢI có shape `{code: "df.<category>", message, retryable: bool, details?}` — trace FR-10-02.
- Code PHẢI thuộc một catalog cố định; tool không được trả mã lỗi không có trong catalog — trace FR-10-08.
- Catalog ban đầu PHẢI có ít nhất: `df.invalid_argument`, `df.unauthorized`, `df.permission_denied`, `df.not_found`, `df.conflict`, `df.precondition_failed`, `df.rate_limited`, `df.quota_exceeded`, `df.token_suspended`, `df.timeout`, `df.internal`, `df.evidence_required`, `df.session_not_owned` — trace tất cả ticket DF-E-10 đã đề cập.
- `retryable = true` nghĩa là agent CÓ THỂ retry sau (vd df.timeout, df.rate_limited); `false` cho lỗi semantic (vd df.permission_denied).
- Error PHẢI map sang HTTP status khi route HTTP wrap — trace parity FR-10-08.
- Error message NÊN bao gồm hint hành động (vd "end current session before claiming another").
- Catalog PHẢI được tài liệu hoá ở một file duy nhất + export qua tool discovery (DF-T-10-010).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Mọi error trả về có shape đúng**

```
Given agent gọi tool sai input
When tool trả error
Then response có field code (df.*), message, retryable, details
And code thuộc catalog
```

**AC-2: retryable flag chính xác**

```
Given tool trả df.rate_limited
Then retryable=true và details.retry_after_ms > 0
Given tool trả df.permission_denied
Then retryable=false
```

**AC-3: HTTP parity**

```
Given route HTTP tương ứng tool df_campaign_create trả 403 cho cross-org
When agent gọi cùng request qua MCP
Then MCP trả mã lỗi df.permission_denied
And mapping: df.permission_denied ↔ HTTP 403 được document
```

**AC-4: Code mới phải thêm catalog trước khi dùng**

```
Given developer thêm mã lỗi mới df.foo trong code mà chưa update catalog
When CI catalog check chạy
Then build fail với message "Mã lỗi df.foo not in catalog"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm i18n message (chỉ tiếng Anh ở release Preview để agent đa model parse được).
- KHÔNG bao gồm telemetry log cảm xúc / chi tiết stack trace ra ngoài (chỉ trong audit log internal).
- KHÔNG bao gồm mã lỗi platform-specific — DF-E-08.

## 7. Kế hoạch triển khai

**Contract / API** (`layer:contract`)

- [ ] File `mcp/error_catalog.yaml`.
- [ ] Mapping df.* ↔ HTTP status.
- [ ] Documentation per code.

**Backend** (`layer:backend`)

- [ ] Utility throw error có structure chuẩn.
- [ ] Middleware map exception → response shape.
- [ ] CI script check code dùng trong source thuộc catalog.

**Documentation** (`layer:docs`)

- [ ] Doc catalog kèm ví dụ.
- [ ] Warning Preview.

**Test** (`layer:test`)

- [ ] Test response shape cho mọi mã lỗi.
- [ ] Test CI catalog check fail với code lạ.
- [ ] Test retryable flag.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-013-01 | Positive | Tool df_tap input sai | Gọi | Error có code df.invalid_argument, retryable=false, message rõ |
| TC-DF-T-10-013-02 | Positive | Tool đụng rate-limit | Gọi | Error df.rate_limited, retryable=true, details.retry_after_ms |
| TC-DF-T-10-013-03 | Negative | Code df.foo không có trong catalog dùng trong code | CI check | Build fail |
| TC-DF-T-10-013-04 | Negative | Tool trả raw exception trace không có shape chuẩn | Test | Test fail; middleware bắt buộc wrap |
| TC-DF-T-10-013-05 | Edge | Tool internal error 500 | Quan sát | Error df.internal, retryable=true, message generic; stack trace KHÔNG lộ ra agent |
| TC-DF-T-10-013-06 | Positive | Mapping df.* ↔ HTTP | Audit | Doc đầy đủ; spot-check 5 code |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-002.

**Chặn:** Mọi tool ticket khi merge final (DF-T-10-004 → DF-T-10-012 đã đề cập code, cần catalog formal).

**Phụ thuộc giữa Epic:** Không trực tiếp; reuse pattern DF-E-01.

**Rủi ro:**

- **Code drift khi nhiều dev thêm mới:** CI catalog check.
- **Message bị dịch sai nghĩa khi i18n sau:** giữ message tiếng Anh ổn định, hint hành động tách field details.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Catalog file đầy đủ ≥ 13 code.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md FR-10-02, FR-10-08](../../official_docs/modules/10-mcp-agent-tools.md).
- **Nhóm người dùng:** Automation Builder, AI Operations Supervisor (Preview).
- **Thuật ngữ:** df_* tool.
