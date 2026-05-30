# DF-T-10-014 — Preview disclosure banner trên dashboard

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-014 |
| **Title** | Preview disclosure banner — warning UI ở mọi entry MCP trong dashboard |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 2 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `module:frontend`, `layer:frontend`, `type:feature`, `persona:ai-ops` |
| **Truy vết — FR refs** | FR-10-01, FR-10-09 |
| **Truy vết — UC refs** | UC-10-01, UC-10-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Người dùng dashboard có thể vô tình nhầm tính năng MCP là sản phẩm cốt lõi — không có banner thì khó truyền tải trạng thái Preview. Ticket này thêm một disclosure banner hiển thị ở mọi entry point liên quan MCP trong dashboard: trang token MCP, audit log MCP, tool registry view, tool test sandbox.

Persona: **AI Operations Supervisor (Preview)** thấy banner mỗi lần vào trang MCP; **Admin** thấy khi cấp token MCP.

> **Cảnh báo Preview:** Banner này tự nó cũng là minh bạch hóa trạng thái Preview. Phải hiển thị bằng ngôn ngữ rõ ràng (không kỹ thuật), kèm link tới tài liệu module 10.

Ưu tiên P2 — không block backend nhưng là yêu cầu thực thi DoD DF-E-10.

Đọc nhanh cho dev: ticket này chỉ thêm disclosure UI cho vùng MCP Preview. Phần bắt buộc là banner ở mọi entry MCP, modal consent khi tạo token và hiển thị `contract_version`; không build sandbox, audit dashboard đầy đủ hoặc thay đổi backend MCP contract.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview) hoặc Admin
> **Tôi muốn** thấy banner cảnh báo "MCP Agent Tools đang ở trạng thái Preview / Experimental — contract có thể thay đổi" trên mọi trang MCP của dashboard
> **Để** tôi và đồng nghiệp không nhầm tưởng đây là tính năng GA và có quyết định tích hợp phù hợp.

## 4. Yêu cầu chức năng

- Dashboard PHẢI hiển thị banner Preview trên các trang MCP: `/dashboard/mcp/tokens`, `/dashboard/mcp/audit-log`, `/dashboard/mcp/tools`, `/dashboard/mcp/sandbox` (nếu có) — trace FR-10-01.
- Banner PHẢI có nội dung: trạng thái Preview, cam kết "no GA SLA", link tới tài liệu module 10, link release note Preview gần nhất.
- Banner PHẢI hiển thị `contract_version` lấy từ MCP server (qua DF-T-10-010) — trace FR-10-02.
- Banner PHẢI có thể dismiss tạm thời (session-scope), nhưng KHÔNG dismiss vĩnh viễn — phải xuất hiện lại sau reload.
- Khi user cấp token MCP, dashboard PHẢI hiện modal confirm với nội dung Preview rõ ràng, yêu cầu tick "Tôi hiểu đây là Preview" trước khi submit.
- Banner PHẢI có biến i18n cho mọi locale dashboard hỗ trợ (vd vi, en) — trace FR-11-04.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Banner xuất hiện trên trang MCP**

```
Given user thuộc org X login dashboard
When mở /dashboard/mcp/tokens
Then banner Preview hiển thị ngay đầu trang
And nội dung khớp wording đã duyệt
And link tới tài liệu module 10 và release note hoạt động
```

**AC-2: Modal confirm khi cấp token**

```
Given user mở dialog "Create new MCP token"
When user nhấn Submit mà chưa tick checkbox "Tôi hiểu đây là Preview"
Then Submit bị disabled hoặc reject với cảnh báo
When user tick checkbox + Submit
Then token được tạo và audit log ghi consent
```

**AC-3: Banner không tắt vĩnh viễn**

```
Given user dismiss banner ở session 1
When user reload trang hoặc bắt đầu session 2
Then banner xuất hiện lại
```

**AC-4: Banner đa ngôn ngữ**

```
Given dashboard hỗ trợ vi và en
When user đổi locale sang en
Then banner text hiển thị tiếng Anh
And không có chuỗi tiếng Việt sót
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm dashboard audit log MCP đầy đủ — DF-E-11 ticket admin/audit.
- KHÔNG bao gồm sandbox UI để test tool — open question.
- KHÔNG bao gồm token issuance UX chi tiết — chỉ modal confirm.
- KHÔNG bao gồm telemetry click banner — basic counter là đủ.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Component `PreviewBanner` dùng chung cho mọi trang MCP.
- [ ] Lấy contract_version từ MCP server (qua proxy hoặc generated client).
- [ ] Modal confirm khi cấp token với checkbox bắt buộc.
- [ ] i18n string cho vi + en.

**Contract / API** (`layer:contract`)

- [ ] Endpoint trả contract_version (đã có ở DF-T-10-010).
- [ ] Audit log consent khi cấp token (đầu mối với DF-T-10-011).

**Documentation** (`layer:docs`)

- [ ] Doc wording banner đã duyệt.
- [ ] Update tài liệu module 11 (dashboard) phần Preview.

**Test** (`layer:test`)

- [ ] Component test banner render đúng.
- [ ] E2E test modal confirm token.
- [ ] Test i18n switch.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-014-01 | Positive | Login user có quyền MCP | Mở /dashboard/mcp/tokens | Banner hiển thị, link đúng |
| TC-DF-T-10-014-02 | Positive | Mở modal create token | Submit chưa tick consent | Reject |
| TC-DF-T-10-014-03 | Positive | Tick consent + Submit | Tạo token | Token tạo + audit consent |
| TC-DF-T-10-014-04 | Edge | Dismiss banner → reload | Reload | Banner xuất hiện lại |
| TC-DF-T-10-014-05 | Positive | Đổi locale en | Reload | Banner tiếng Anh |
| TC-DF-T-10-014-06 | Negative | MCP server down → không lấy được contract_version | Mở trang | Banner vẫn hiển thị warning kèm "contract version unknown" |
| TC-DF-T-10-014-07 | Negative | User chưa có quyền MCP token admin | Mở trang MCP tokens | Trang bị chặn 403 và không render CTA tạo token |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-010 (contract_version), DF-T-10-011 (audit consent log).

**Chặn:** Không.

**Phụ thuộc giữa Epic:**

- **DF-E-11 (Frontend & Dashboard)** — app shell, i18n routing, generated client.

**Rủi ro:**

- **Wording không đủ rõ:** review nội bộ + có thể qua copy review.
- **Banner gây UX phiền:** dismissable session-scope đủ; không cho dismiss vĩnh viễn vì là disclosure bắt buộc.

**Phụ thuộc bên ngoài:** Generated client cập nhật endpoint contract_version.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Component test + E2E test green.
- [ ] Test case TC-DF-T-10-014-* map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật wording banner.
- [ ] Telemetry: counter banner_view, counter consent_token_accept.
- [ ] Code review ≥ 1 approve + UX reviewer.
- [ ] Release notes Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**
- [ ] Banner đã hiển thị đúng trên cả 2 locale (vi, en).

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md §1, §8](../../official_docs/modules/10-mcp-agent-tools.md), [11-frontend-dashboard.md FR-11-04](../../official_docs/modules/11-frontend-dashboard.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview), Admin.
- **Thuật ngữ:** Preview, MCP, df_* tool.
- **Lộ trình:** [99-roadmap-and-faq.md §4.3](../../official_docs/99-roadmap-and-faq.md).
