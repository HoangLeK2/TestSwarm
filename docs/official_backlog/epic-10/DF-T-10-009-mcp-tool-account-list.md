# DF-T-10-009 — Tool `df_account_list` — agent đọc account khả dụng

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-009 |
| **Title** | Tool `df_account_list` — agent enumerate account / account-group khả dụng |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 2 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:contract`, `type:feature`, `persona:ai-ops`, `risk:auth` |
| **Truy vết — FR refs** | FR-10-02, FR-10-05, FR-10-08 |
| **Truy vết — UC refs** | UC-10-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Agent đôi khi cần biết "đang có account nào trong account-group X có thể gán vào scenario" để chọn trước khi run. Tool `df_account_list` wrap route list account DF-E-07 với output schema **tối giản**: agent KHÔNG được phép thấy credential, chỉ thấy alias/handle, account-group, trạng thái health.

Persona: **AI Operations Supervisor (Preview)** là người chịu trách nhiệm chính.

> **Cảnh báo Preview:** Tool đụng tới dữ liệu nhạy cảm (account social). Schema output phải tối giản, KHÔNG tiết lộ credential, recovery email, hay metadata định danh quá chi tiết. Đây là phần mở rộng nghiên cứu.

Ưu tiên P3 — không phải critical, là utility.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** agent gọi `df_account_list(account_group_id, platform)` để biết account nào khả dụng
> **Để** agent chọn account phù hợp khi gọi `df_campaign_create` hoặc khi đề xuất binding scenario ↔ account.

## 4. Yêu cầu chức năng

- Tool PHẢI yêu cầu MCP_AUTH_TOKEN — trace FR-10-05.
- Tool PHẢI nhận filter: `account_group_id`, `platform`, `status` — trace FR-10-02.
- Output PHẢI tối giản: `account_id`, `display_handle`, `platform`, `account_group_id`, `health_status` (healthy / warning / checkpointed / disabled). KHÔNG bao gồm credential, recovery email, hay cookie.
- Tool PHẢI tôn trọng ownership org — trace FR-10-20.
- Tool PHẢI ghi audit log (DF-T-10-011).
- Tool NÊN hỗ trợ pagination như device.list.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List account thành công, không có credential trong output**

```
Given org X có 50 account thuộc account-group G1
And agent dùng MCP_AUTH_TOKEN của org X
When agent gọi df_account_list(account_group_id=G1)
Then trả về 50 account với schema tối giản
And không có field password / cookie / recovery_email
And audit log có entry
```

**AC-2: Filter theo platform và status**

```
Given mix account Facebook/TikTok, 30 healthy + 20 checkpointed
When agent gọi df_account_list(platform="facebook", status="healthy")
Then chỉ trả về account Facebook healthy
```

**AC-3: Cross-org blocked**

```
Given account-group thuộc org Y; token org X
When agent gọi df_account_list(account_group_id của org Y)
Then df.permission_denied + audit cross-org
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm tạo / sửa / xóa account — admin only, không qua MCP.
- KHÔNG bao gồm lấy credential — security boundary.
- KHÔNG bao gồm bind account vào device — DF-E-07.
- KHÔNG bao gồm account recovery flow.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Handler df_account_list.
- [ ] Filter ownership.
- [ ] Schema mapper tối giản (loại credential).
- [ ] Audit log.

**Contract / API** (`layer:contract`)

- [ ] Registry + schema.
- [ ] http_route_ref DF-E-07.

**Documentation** (`layer:docs`)

- [ ] Doc + warning Preview + cảnh báo schema không credential.

**Test** (`layer:test`)

- [ ] Test schema không leak credential (grep response).
- [ ] Cross-org test.
- [ ] Pagination test.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-009-01 | Positive | 50 account trong group | Gọi tool | 50 entry tối giản, audit log |
| TC-DF-T-10-009-02 | Positive | Filter platform=facebook | Gọi tool | Chỉ Facebook account |
| TC-DF-T-10-009-03 | Negative | Token device-scoped | Gọi tool | df.permission_denied |
| TC-DF-T-10-009-04 | Negative | account_group org khác | Gọi tool | df.permission_denied + audit cross-org |
| TC-DF-T-10-009-05 | Edge | Grep response cho từ "password"/"cookie" | Inspect | Không tìm thấy; schema không leak credential |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-002, DF-T-10-003.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** **DF-E-07** (Account & Account Group).

**Rủi ro:**

- **Leak credential do schema sai:** test grep CI bắt buộc.
- **Agent dùng list account để hồ sơ hóa target:** ngoài phạm vi Device Farm; doc khuyến nghị legal review trước khi dùng cho purpose ngoài thu thập dữ liệu.

**Phụ thuộc bên ngoài:** Service account DF-E-07.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] CI grep test confirms no credential field leak.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Code review ≥ 1 approve + security reviewer.
- [ ] Release notes Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md FR-10-02, FR-10-05](../../official_docs/modules/10-mcp-agent-tools.md).
- **Module liên quan:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview).
- **Thuật ngữ:** Account, Account group.
