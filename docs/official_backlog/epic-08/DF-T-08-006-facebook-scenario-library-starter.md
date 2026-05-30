# DF-T-08-006 — Facebook scenario library: starter pack

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-006 |
| **Title** | Facebook scenario library — starter pack template (crawl post, crawl comment, engage, monitor) |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Ready |
| **Labels** | `module:social-ext`, `layer:backend`, `layer:frontend`, `layer:docs`, `type:feature`, `platform:facebook`, `coverage:L2`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-08-01, FR-08-02, FR-08-03, FR-08-11, FR-08-12 |
| **Truy vết — UC refs** | UC-08-05, UC-08-06, UC-08-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Có parser (DF-T-08-004) và handler (DF-T-08-005) chưa đủ để Facebook đạt trạng thái L2 Active đầy đủ — checklist artifact trong đặc tả module mục 7.2 yêu cầu "Scenario template ví dụ user-facing". Không có scenario reference, Automation Builder phải build từ đầu mỗi lần — dễ ra scenario sai pattern, không tận dụng đúng UI-gated, không dùng đúng dedupe key.

Ticket này cung cấp **starter pack** gồm 4 scenario template reference cho Facebook: (1) crawl post từ group, (2) crawl comment chain dưới 1 post, (3) engage (like + comment) batch, (4) monitor page định kỳ. Mỗi template dùng đúng naming canonical, content type qualified, có error policy chuẩn, có comment giải thích từng step. Template được expose qua frontend flow editor "Templates" panel và có thể clone-then-modify.

Persona hưởng lợi chính: **Automation Builder** mới onboard sản phẩm — dùng template làm starting point thay vì xây từ rỗng.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** có sẵn 4 scenario template Facebook (crawl post, crawl comment, engage, monitor) trong flow editor
> **Để** clone-then-modify thay vì build từ đầu, đảm bảo dùng đúng naming canonical, content type qualified, và error policy chuẩn

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có 4 scenario template Facebook reference được publish vào template library — trace FR-08-01, FR-08-02.
- Mỗi template PHẢI dùng naming canonical `fb_*` và content type qualified `fb_post` / `fb_comment` — trace FR-08-01, FR-08-03.
- Mỗi template PHẢI có comment giải thích mục đích từng step (để Builder mới đọc hiểu được) — trace FR-08-11.
- Hệ thống PHẢI expose endpoint `GET /api/scenarios/templates?platform=facebook` trả về 4 template.
- Frontend flow editor PHẢI có "Templates" panel hiển thị 4 template, có thumbnail và mô tả ngắn.
- Hệ thống PHẢI cho phép clone template thành scenario mới có thể edit — trace FR-08-12.
- Mỗi template PHẢI khai báo error policy phù hợp use case (vd crawl post: retry 3 lần khi `extract` fail; engage: fail-fast).
- Template PHẢI có golden test bảo vệ: thay đổi template sai naming convention bị reject ở CI.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: 4 template publish vào library**

```
Given Device Farm boot xong, Facebook extension nạp
When Automation Builder gọi GET /api/scenarios/templates?platform=facebook
Then trả về 4 template với metadata: name, description, step count, recommended use case
And mỗi template body chứa scenario JSON hợp lệ qua schema validator
```

**AC-2: Template dùng naming canonical**

```
Given template "crawl_group_posts"
When inspect template body
Then mọi step type bắt đầu bằng "fb_" hoặc generic step (tap, swipe, save_extraction)
And mọi extraction strategy bắt đầu bằng "fb_"
And mọi content_type là "fb_post" hoặc "fb_comment", không phải "post"/"comment" generic
```

**AC-3: Clone template tạo scenario edit được**

```
Given Automation Builder ở flow editor
When họ chọn template "crawl_comment_chain" và nhấn Clone
Then scenario mới được tạo trong workspace với toàn bộ step copy từ template
And scenario mới có id riêng, không link với template gốc
And Builder edit param (vd post URL) và save thành công
```

**AC-4: CI guard từ chối template sai naming**

```
Given developer sửa template "engage_batch" đổi step name từ `fb_like_post` thành `like_post`
When họ commit và push
Then CI golden test fail với error "template step naming violation: 'like_post' must start with fb_*"
And PR bị block
```

**AC-5: Template hiển thị trong flow editor panel**

```
Given Automation Builder mở flow editor và filter platform = Facebook
When họ click "Templates" panel
Then 4 thumbnail hiển thị: Crawl Group Posts, Crawl Comment Chain, Engage Batch, Monitor Page
And mỗi thumbnail có description ngắn
And click thumbnail mở preview scenario flow
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm template cho platform TikTok / Threads / Instagram — sẽ là backlog khi mỗi platform chuyển sang Active.
- KHÔNG bao gồm template engage advanced (comment AI-generated, smart follow) — sẽ phối hợp DF-E-10 (MCP).
- KHÔNG bao gồm template Facebook Story / Messenger — không trong L2 scope.
- KHÔNG bao gồm versioning template (chỉ có v1.0 ban đầu) — sẽ là tech-debt sau.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Tạo 4 template scenario JSON: crawl_group_posts, crawl_comment_chain, engage_batch, monitor_page
- [ ] Implement template registry và endpoint `GET /api/scenarios/templates`
- [ ] Implement endpoint clone template

**Frontend** (`layer:frontend`)

- [ ] Templates panel trong flow editor
- [ ] Thumbnail rendering cho 4 template
- [ ] Clone button → tạo scenario workspace mới

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho endpoint templates và clone
- [ ] JSON schema validator cho template body (verify naming canonical)

**Documentation** (`layer:docs`)

- [ ] `docs/official_docs/platforms/facebook.md` thêm mục "Scenario templates"
- [ ] Tutorial "Bắt đầu với template Facebook" cho Automation Builder
- [ ] Mỗi template có README mô tả use case

**Test** (`layer:test`)

- [ ] Golden test cho 4 template (validate naming, schema, error policy)
- [ ] Integration test: clone template → edit → dispatch → run thành công trên device
- [ ] Frontend test cho Templates panel

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-006-01 | Positive | Facebook ext nạp, template library publish | GET /api/scenarios/templates?platform=facebook | 200 OK, 4 template với metadata đầy đủ |
| TC-DF-T-08-006-02 | Positive | Automation Builder ở flow editor | Clone template `crawl_group_posts`, edit group_id param, dispatch | Scenario chạy thành công, content_items lưu với `fb_post` qualified |
| TC-DF-T-08-006-03 | Negative | Developer sửa template engage_batch đổi `fb_like_post` thành `like_post` | Commit PR | CI fail với template naming violation, PR block |
| TC-DF-T-08-006-04 | Negative | User không có quyền tạo scenario | Click Clone template | 403 Forbidden, không tạo scenario |
| TC-DF-T-08-006-05 | Edge | Template `crawl_comment_chain` có nested scenario | Clone và dispatch | Nested scenario hoạt động đúng, không vỡ structure |
| TC-DF-T-08-006-06 | Edge | Có 100 user clone cùng template đồng thời | Concurrency test | Mỗi user nhận scenario có id riêng, không conflict |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-004, DF-T-08-005.

**Chặn:** Không (đây là deliverable cuối cùng để Facebook đạt L2 Active checklist).

**Phụ thuộc giữa Epic:**

- **DF-E-04 (Campaign / Scenario)** — template phải dùng scenario JSON schema của Module Campaign.
- **DF-E-11 (Frontend)** — Templates panel UI là phần frontend.

**Rủi ro:**

- **Template outdated khi Facebook UI thay đổi** → giảm thiểu: regression test template hàng tuần trên device pool; alert khi tỷ lệ thành công < 90%.
- **Builder modify template tạo scenario sai pattern** → giảm thiểu: schema validator vẫn áp dụng khi save scenario clone; có warning hint khi step rời pattern canonical.

**Phụ thuộc bên ngoài:** Phụ thuộc Facebook Android app phiên bản tested.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] 4 template JSON validate qua schema validator.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả TC-DF-T-08-006-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/facebook.md` cập nhật.
- [ ] 4 template chạy thành công trên ≥ 3 device thật trong regression test.
- [ ] Frontend Templates panel UI live.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes cập nhật.
- [ ] **Facebook L2 Active checklist artifact đầy đủ** (parser + handler + scenario template + frontend node + test + docs).

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-01, FR-08-02, FR-08-03, FR-08-11, FR-08-12), mục 7.2 (Scenario template ví dụ user-facing artifact).
- **Platform profile:** [facebook.md](../../official_docs/platforms/facebook.md).
- **Module Campaign:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Automation Builder.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Authored scenario flow.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
