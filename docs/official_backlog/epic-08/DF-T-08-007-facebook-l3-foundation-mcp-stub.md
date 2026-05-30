# DF-T-08-007 — Facebook L3 Foundation: MCP guardrail stub

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-007 |
| **Title** | Facebook L3 Foundation — khung khai báo MCP guardrail (allowed action cap, evidence, handoff) |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:social-ext`, `layer:backend`, `layer:contract`, `type:feature`, `platform:facebook`, `coverage:L3`, `persona:ai-ops`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-13 |
| **Truy vết — UC refs** | UC-08-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

L3 cho Facebook đang ở trạng thái **Foundation (preview)** — MCP tool generic `df_*` đã sẵn sàng cho AI agent thao tác Facebook, nhưng bộ guardrail riêng theo platform (allowed action cap, evidence requirement, handoff condition, account safety) chưa được khai báo. Hệ quả: AI Ops Supervisor có thể vận hành AI agent trên Facebook nhưng phải tự áp kỷ luật giám sát thủ công.

Ticket này không hoàn thiện L3 Active (vì cần phối hợp Module 10 MCP và phối hợp policy với Product); ticket này tạo **khung schema** để khai báo guardrail platform-specific theo contract Social Platform Extensions. Khung gồm: schema YAML cho allowed action cap (max action/phút, max/giờ), evidence requirement (screenshot before/after, hierarchy snapshot at decision point), handoff condition (captcha, security checkpoint, abnormal state). Sau khi schema có, Product có thể điền cụ thể policy Facebook và MCP server đọc để enforce runtime.

Persona hưởng lợi: **AI Ops Supervisor** (sau khi schema được điền), **Platform Engineer** (template guardrail cho platform khác noi theo).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một khung schema khai báo MCP guardrail riêng theo platform (Facebook trước, các platform khác sau)
> **Để** Product có thể điền policy cụ thể (action cap, evidence, handoff) và MCP server enforce runtime — đẩy Facebook từ Foundation lên Active L3

## 4. Yêu cầu chức năng

- Hệ thống PHẢI expose interface `PlatformGuardrailSchema` cho phép platform extension khai báo 4 nhóm rule: allowed action cap, evidence requirement, handoff condition, account safety — trace FR-08-13.
- Hệ thống PHẢI có schema YAML cho từng nhóm rule với validator schema.
- Hệ thống PHẢI publish stub guardrail cho Facebook (có khung, giá trị placeholder, đánh dấu rõ "preview, chưa enforce").
- Hệ thống PHẢI expose endpoint `GET /api/social-ext/platforms/{platform}/guardrail` trả về guardrail hiện tại.
- Hệ thống PHẢI mark trạng thái L3 trong response API: "Foundation (preview)" cho Facebook, "Draft (preview)" cho 3 platform còn lại — trace FR-08-13.
- Hệ thống NÊN có cơ chế ghi log mỗi lần guardrail "would block" (dry-run mode) để Product đánh giá impact trước khi enforce.
- Khi guardrail bị thiếu, MCP server PHẢI fall back về behavior generic và log warning.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Schema guardrail có 4 nhóm rule**

```
Given Facebook extension đăng ký guardrail stub theo schema mới
When inspect schema YAML
Then có đủ 4 section: allowed_action_cap, evidence_requirement, handoff_condition, account_safety
And mỗi section có comment "PREVIEW — placeholder, not enforced"
And schema validate qua YAML schema validator
```

**AC-2: API expose guardrail trạng thái Foundation**

```
Given Facebook extension nạp với guardrail stub
When client gọi GET /api/social-ext/platforms/facebook/guardrail
Then response 200 với body chứa 4 section
And metadata field "status" = "Foundation (preview)"
And metadata field "enforced" = false
And metadata field "version" = "0.1.0"
```

**AC-3: Dry-run log khi guardrail would block**

```
Given AI agent qua MCP gọi tool `df_action_like` 100 lần trong 1 phút trên Facebook
And guardrail Facebook khai báo placeholder cap "max 10 like/phút" với enforce=false
When 11th call đến
Then MCP server log warning "guardrail would block: action cap exceeded"
And action vẫn được thực thi (dry-run, không enforce)
And metric `guardrail_dry_run_block_total` tăng
```

**AC-4: 3 platform Draft target không có guardrail**

```
Given TikTok / Threads / Instagram extension chỉ có draft (DF-T-08-008/010/012)
When client gọi GET /api/social-ext/platforms/tiktok/guardrail
Then response 200 với body rỗng và metadata "status" = "Draft (preview)"
And không lỗi (gracefully degrade)
And log "tiktok guardrail not declared yet — generic MCP behavior applies"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm enforcement runtime của guardrail — đây là Foundation, không phải Active.
- KHÔNG bao gồm guardrail cho TikTok / Threads / Instagram — sẽ có khi platform tương ứng chuyển sang Active.
- KHÔNG bao gồm policy nội dung cụ thể (vd "max 10 like/phút") — đây là quyết định của Product/Compliance, không thuộc engineering.
- KHÔNG bao gồm MCP tool implementation — thuộc DF-E-10.
- KHÔNG bao gồm handoff workflow end-to-end (UI để Supervisor nhận handoff) — sẽ là backlog Q3.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement interface `PlatformGuardrailSchema`
- [ ] Implement YAML schema validator
- [ ] Implement dry-run mode logger
- [ ] Implement fallback behavior khi guardrail thiếu

**Contract / API** (`layer:contract`)

- [ ] YAML schema cho 4 nhóm rule (allowed_action_cap, evidence_requirement, handoff_condition, account_safety)
- [ ] OpenAPI cho endpoint guardrail
- [ ] Schema versioning theo SemVer

**Documentation** (`layer:docs`)

- [ ] Tutorial "Khai báo guardrail platform-specific"
- [ ] Cập nhật `docs/official_docs/platforms/facebook.md` mục 6 (L3 Foundation) với link tới schema
- [ ] Document dry-run mode và cách Product đánh giá impact

**Test** (`layer:test`)

- [ ] Unit test YAML schema validator
- [ ] Integration test dry-run log
- [ ] Integration test fallback behavior khi guardrail thiếu

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-007-01 | Positive | Facebook ext nạp với guardrail stub | GET /api/social-ext/platforms/facebook/guardrail | 200 OK, 4 section đúng schema, status "Foundation (preview)" |
| TC-DF-T-08-007-02 | Positive | Stub guardrail có cap 10 like/phút, enforce=false | AI agent gọi 11 like/phút | Action 11 vẫn thực thi; log warning dry-run block; metric tăng |
| TC-DF-T-08-007-03 | Negative | YAML guardrail malformed (sai schema) | Boot Device Farm | Extension reject với `GUARDRAIL_SCHEMA_INVALID`; chỉ rõ field sai |
| TC-DF-T-08-007-04 | Negative | TikTok extension chưa khai báo guardrail | GET /api/social-ext/platforms/tiktok/guardrail | 200 OK, body rỗng, status "Draft (preview)"; warning log |
| TC-DF-T-08-007-05 | Edge | Facebook guardrail bump major version (0.1.0 → 1.0.0) | Migrate guardrail | Schema compatibility check; behavior thay đổi từ Foundation → Active (preview) khi enforce=true; release note required |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-005.

**Chặn:** Future work khi chuyển Facebook L3 Foundation → Active.

**Phụ thuộc giữa Epic:**

- **DF-E-10 (MCP Agent Tools)** — MCP server đọc guardrail schema để enforce. Cần phối hợp định nghĩa hook point.

**Rủi ro:**

- **Schema thiết kế chưa đủ flexible cho platform thứ năm** → giảm thiểu: review schema với 2 Platform Engineer trước merge, schema có version để extend sau.
- **Dry-run log volume lớn ảnh hưởng performance** → giảm thiểu: log sampling, metric thay vì log raw.
- **Product chưa sẵn sàng điền policy cụ thể** → mitigate: stub có placeholder, không block Facebook L2 Active.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả TC-DF-T-08-007-* map sang test tự động.
- [ ] YAML schema commit và publish.
- [ ] Tài liệu cập nhật `docs/official_docs/platforms/facebook.md` mục 6.
- [ ] OpenAPI endpoint mới đã commit.
- [ ] Telemetry: metric dry-run block, log structured.
- [ ] Code review ≥ 1 approve từ owner DF-MOD-08 và DF-MOD-10.
- [ ] Release notes ghi rõ "L3 Foundation — preview, not enforced".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-13), mục 7 (L3 Foundation), mục 8 (giới hạn L3).
- **Platform profile:** [facebook.md](../../official_docs/platforms/facebook.md) — mục 6 (L3 Foundation).
- **Module MCP:** [10-mcp-agent-tools.md](../../official_docs/modules/10-mcp-agent-tools.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — mục 4.4 L3 Preview.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — AI Operations Supervisor.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Guardrail, Handoff.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — L3 platform-specific.
