# DF-T-10-008 — Tool `df_content_query` / `df_save_extraction` — content tool

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-008 |
| **Title** | Tool `df_content_query` + `df_save_extraction` + `df_get_content_item` — agent đọc/ghi content + evidence |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:contract`, `type:feature`, `persona:ai-ops`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-10-05, FR-10-08, FR-10-11, FR-10-15, FR-10-19 |
| **Truy vết — UC refs** | UC-10-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Agent là người "quan sát" device và phải persist quan sát thành evidence để supervisor review (FR-10-11). Module 10 yêu cầu tool content cho phép agent: query content khả dụng (`df_content_query`), save extraction mới (`df_save_extraction`), và đọc 1 item cụ thể (`df_get_content_item`). Đây cũng là cầu nối để Social Data Operator tiêu thụ dữ liệu agent thu thập.

Persona chính: **AI Operations Supervisor (Preview)** (cần evidence); persona phụ: **Social Data Operator** (tiêu thụ content).

> **Cảnh báo Preview:** Tool này persist dữ liệu thật vào content store. Sai schema sẽ gây rác. Khuyến nghị: collection riêng cho output Preview agent để dễ dọn nếu cần.

Ưu tiên P2.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** agent gọi `df_save_extraction` để persist screenshot + hierarchy + observation thành content item kèm artifact
> **Để** tôi có evidence review sau session và Social Data Operator có thể tiêu thụ dữ liệu.

## 4. Yêu cầu chức năng

- Tool PHẢI yêu cầu MCP_AUTH_TOKEN — trace FR-10-05, FR-10-19.
- `df_content_query` PHẢI hỗ trợ filter `collection_id`, `content_type`, `platform`, `time_range`, `cursor`, `limit` — trace FR-10-19.
- `df_save_extraction` PHẢI accept: `content_type` (platform-qualified, vd `fb_post`, `tiktok_video`), `collection_id`, `payload` (object), `artifact_refs[]` (screenshot/hierarchy đã upload) — trace FR-10-19, FR-10-15.
- `df_get_content_item` PHẢI trả về detail content kèm danh sách artifact link — trace FR-10-19.
- Tool PHẢI tôn trọng ownership organization — trace FR-10-20.
- Action save extraction PHẢI bị reject nếu thiếu evidence với tool có flag `require_evidence = true` (theo guardrail) — trace FR-10-11.
- Tool PHẢI ghi audit log (DF-T-10-011).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Save extraction kèm evidence thành công**

```
Given session S1 + collection C1 thuộc org của token
When agent gọi df_save_extraction(content_type="fb_post", collection_id=C1, payload={...}, artifact_refs=["art-1","art-2"])
Then trả về content_id
And content item gắn evidence artifact
And audit log có entry input đầy đủ
```

**AC-2: Query content theo filter**

```
Given collection C1 có 1000 content_item
When agent gọi df_content_query(collection_id=C1, content_type="fb_post", limit=50)
Then trả về 50 item phù hợp + next_cursor
```

**AC-3: Save extraction không có evidence khi require_evidence**

```
Given guardrail platform fb có require_evidence=true cho content_type="fb_post"
When agent gọi df_save_extraction với artifact_refs=[]
Then df.precondition_failed "evidence required for fb_post"
And không persist content
```

**AC-4: Cross-org blocked**

```
Given collection C2 thuộc org Y; token org X
When agent gọi df_content_query(collection_id=C2)
Then df.permission_denied + audit cross-org
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm upload artifact binary qua MCP — agent upload qua route artifact riêng trước rồi đưa artifact_ref.
- KHÔNG bao gồm enrich/process content — DF-E-06.
- KHÔNG bao gồm bulk save > 100 item / call — chia batch.
- KHÔNG bao gồm content delete — admin only, không qua MCP.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Handler 3 tool.
- [ ] Ownership check.
- [ ] Guardrail evidence check.
- [ ] Audit log.

**Contract / API** (`layer:contract`)

- [ ] Registry + schema.
- [ ] http_route_ref DF-E-06.

**Documentation** (`layer:docs`)

- [ ] Doc + warning Preview.
- [ ] Ví dụ payload theo platform.

**Test** (`layer:test`)

- [ ] Unit + integration test.
- [ ] Test require_evidence.
- [ ] Test cross-org.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-008-01 | Positive | Token user-scoped, collection cùng org | df_save_extraction với artifact_refs hợp lệ | content_id trả về, audit log |
| TC-DF-T-10-008-02 | Positive | Collection 1000 item | df_content_query limit=50 | 50 item + next_cursor |
| TC-DF-T-10-008-03 | Negative | require_evidence=true, artifact_refs=[] | df_save_extraction | df.precondition_failed |
| TC-DF-T-10-008-04 | Negative | Collection org khác | df_content_query | df.permission_denied + audit cross-org |
| TC-DF-T-10-008-05 | Edge | payload 5 MB JSON | df_save_extraction | df.invalid_argument nếu > limit (mặc định 2 MB), khuyến nghị split |
| TC-DF-T-10-008-06 | Negative | artifact_ref trỏ tới artifact đã hết hạn / không tồn tại | df_save_extraction | df.invalid_argument với danh sách ref sai |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-002, DF-T-10-003.

**Chặn:** DF-T-10-011 (audit ghi nội dung content tool call).

**Phụ thuộc giữa Epic:** **DF-E-06** (Content Extraction & Artifact).

**Rủi ro:**

- **Agent persist payload nhiễu loạn:** content_type validate theo platform; doc khuyến nghị collection riêng cho Preview.
- **Bypass evidence requirement:** test guard.
- **Artifact orphan ref:** check tồn tại artifact trước khi commit content.

**Phụ thuộc bên ngoài:** Service content + artifact store DF-E-06.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter content_via_mcp, histogram payload size.
- [ ] Code review ≥ 1 approve + owner Epic-06.
- [ ] Release notes Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md FR-10-11, FR-10-15, FR-10-19](../../official_docs/modules/10-mcp-agent-tools.md).
- **Module liên quan:** [06-content-extraction-artifacts.md](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview), Social Data Operator.
- **Thuật ngữ:** Content item, Artifact.
