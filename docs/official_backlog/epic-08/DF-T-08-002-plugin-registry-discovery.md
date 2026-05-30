# DF-T-08-002 — Plugin registry & discovery

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-002 |
| **Title** | Plugin registry & discovery — runtime đăng ký và tra cứu platform extension |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Ready |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:agnostic`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-05, FR-08-06, FR-08-10 |
| **Truy vết — UC refs** | UC-08-01, UC-08-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi Device Farm có một platform thật chạy production (Facebook) và ba platform Draft target khác (TikTok, Threads, Instagram), runtime cần biết "platform nào đang được nạp, ai sở hữu step type nào, parser nào ứng với strategy nào". Nếu không có một registry tập trung, scenario executor sẽ phải hard-code các step type platform-specific — ngược lại nguyên tắc "mọi hành vi platform-specific là dữ liệu đầu vào".

Ticket này hiện thực hóa **plugin registry runtime** — khi Device Farm boot, registry quét các package đã đăng ký, validate naming, đăng ký step type và extraction strategy vào executor dispatch table, và expose API để frontend / MCP / observability tra cứu "đang có platform nào active". Đồng thời, registry là điểm enforce ranh giới rằng không có platform code chạy bên ngoài scenario step model — vi phạm phát hiện ở boot time, không phải runtime.

Persona hưởng lợi: **Platform Engineer** (debug khi platform không nạp được), **Automation Builder** (tra step type khả dụng trên platform mục tiêu qua frontend), **Operator** (xem trạng thái platform active trong dashboard).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một plugin registry tự động đăng ký platform extension khi boot và expose API tra cứu
> **Để** scenario executor dispatch đúng handler/parser, frontend liệt kê đúng step type khả dụng, và team có một nguồn chân lý "platform nào đang active"

## 4. Yêu cầu chức năng

- Hệ thống PHẢI quét và đăng ký tự động các platform extension đã cài đặt tại boot time — trace FR-08-05, FR-08-06.
- Hệ thống PHẢI validate đầy đủ contract (parser + handler + scenario lib + content type schema) trước khi đăng ký — extension thiếu artifact bị reject — trace FR-08-12.
- Hệ thống PHẢI expose endpoint `GET /api/social-ext/platforms` trả về danh sách platform đang active kèm metadata (version, coverage level, step type count, strategy count) — trace FR-08-06.
- Hệ thống PHẢI expose endpoint `GET /api/social-ext/platforms/{platform}/steps` trả về danh sách step type và extraction strategy của platform đó.
- Hệ thống PHẢI dispatch step trong scenario executor qua registry lookup, không hard-code — trace FR-08-05.
- Hệ thống PHẢI log boot-time discovery summary (số platform nạp, số platform reject, lý do reject).
- Hệ thống NÊN emit metric `plugin_registry_active_platforms` (gauge) cho observability.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Boot-time discovery nạp Facebook**

```
Given Facebook extension đã được cài đặt theo contract DF-T-08-001
And Device Farm bắt đầu boot
When boot sequence chạy đến phase plugin discovery
Then Facebook extension được nạp vào registry
And step type `fb_tap_comment_button` và strategy `fb_posts`, `fb_comments` xuất hiện trong dispatch table
And metric `plugin_registry_active_platforms` = 1
And log boot summary ghi "loaded 1 platform: facebook v1.0.0"
```

**AC-2: Reject extension thiếu artifact**

```
Given một extension giả mạo "fake_tt" chỉ có parser nhưng không có handler
When Device Farm boot
Then extension fake_tt bị reject ở phase discovery
And log ghi rõ "fake_tt rejected: missing PlatformHandler"
And metric `plugin_registry_active_platforms` không tính fake_tt
And Device Farm vẫn boot xong với các extension hợp lệ khác
```

**AC-3: API list platforms trả về metadata đúng**

```
Given registry đã nạp Facebook
When client gọi GET /api/social-ext/platforms
Then trả về danh sách [{name: "facebook", version: "1.0.0", coverage: "L2-Active", step_count: 1, strategy_count: 2}]
And response < 500 ms
And payload có schema OpenAPI đã document
```

**AC-4: Scenario executor dispatch qua registry**

```
Given Facebook extension đã đăng ký step `fb_tap_comment_button`
And scenario chứa step `fb_tap_comment_button`
When scenario executor chạy tới step đó
Then executor lookup registry để tìm handler
And dispatch về FacebookHandler.execute()
And không có hard-coded if/else cho platform Facebook trong executor code
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm runtime load/unload (hot reload) — sẽ xử lý trong DF-T-08-003.
- KHÔNG bao gồm version migration — sẽ xử lý trong DF-T-08-003.
- KHÔNG bao gồm feature flag per-org để bật/tắt platform — sẽ xử lý trong DF-T-08-014.
- KHÔNG bao gồm UI dashboard hiển thị platform status — sẽ xử lý trong DF-E-11 (Frontend).
- KHÔNG bao gồm MCP tool expose platform list cho AI agent — thuộc DF-E-10.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Cài đặt class `PluginRegistry` với 3 method chính: `discover()`, `register()`, `lookup()`
- [ ] Cài đặt boot hook chạy `discover()` ở phase sau auth/db init
- [ ] Cài đặt dispatch table mapping `step_type` → handler instance, `strategy` → parser instance, `content_type` → schema instance
- [ ] Cài đặt error handling: extension reject không làm vỡ boot

**Contract / API** (`layer:contract`)

- [ ] Endpoint `GET /api/social-ext/platforms`
- [ ] Endpoint `GET /api/social-ext/platforms/{platform}/steps`
- [ ] OpenAPI schema cho cả 2 endpoint
- [ ] Authentication: yêu cầu JWT user, role read-only platform list cho mọi role

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/modules/social-ext-contract.md` mục registry behavior
- [ ] Document boot sequence phase plugin discovery
- [ ] Thêm troubleshooting guide khi extension không nạp

**Test** (`layer:test`)

- [ ] Unit test cho PluginRegistry với mock extension
- [ ] Integration test: boot có Facebook → endpoint list trả về Facebook
- [ ] Integration test: boot có extension thiếu artifact → reject + log đúng
- [ ] Performance test: endpoint list < 500 ms với 10 platform giả

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-002-01 | Positive | Facebook extension installed, Device Farm chưa boot | Boot Device Farm | Registry nạp Facebook; metric `plugin_registry_active_platforms` = 1; endpoint `/api/social-ext/platforms` trả về Facebook |
| TC-DF-T-08-002-02 | Positive | Registry đã nạp Facebook | Gọi `GET /api/social-ext/platforms/facebook/steps` | Response 200 với danh sách step `fb_tap_comment_button` và strategy `fb_posts`, `fb_comments` |
| TC-DF-T-08-002-03 | Negative | Extension `fake_tt` thiếu PlatformHandler | Boot Device Farm | Extension bị reject; log ghi rõ lý do; boot không fail; registry không chứa `fake_tt` |
| TC-DF-T-08-002-04 | Negative | Client không có JWT hợp lệ | Gọi `GET /api/social-ext/platforms` | Response 401 Unauthorized |
| TC-DF-T-08-002-05 | Edge | Có 2 extension đăng ký cùng tên platform "facebook" | Boot Device Farm | Boot fail-fast với error `PLUGIN_DUPLICATE_PLATFORM`; chỉ rõ 2 package conflict |
| TC-DF-T-08-002-06 | Edge | 0 platform extension được cài đặt | Boot Device Farm | Registry boot thành công; endpoint trả về list rỗng; scenario có step platform-specific báo "platform not registered" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001.

**Chặn:** DF-T-08-003, DF-T-08-004, DF-T-08-005, DF-T-08-014.

**Phụ thuộc giữa Epic:**

- **DF-E-04 (Campaign / Scenario executor)** — executor phải dispatch step qua registry lookup, không hard-code. Cần phối hợp với owner Module Campaign.

**Rủi ro:**

- **Boot time tăng do discovery phase** → giảm thiểu: parallel discovery cho từng extension, log warning nếu phase > 5s.
- **Extension nạp fail nhưng không log rõ làm Platform Engineer khó debug** → giảm thiểu: log structured với extension name + lý do reject + stack trace.
- **API list platform expose thông tin nội bộ** → giảm thiểu: chỉ trả metadata public, không lộ implementation detail.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage ≥ 80% trên file thay đổi.
- [ ] Tất cả test case TC-DF-T-08-002-* được map sang test tự động.
- [ ] Tài liệu kỹ thuật `docs/modules/social-ext-contract.md` cập nhật.
- [ ] OpenAPI spec cho 2 endpoint mới đã commit.
- [ ] Telemetry: metric `plugin_registry_active_platforms` (gauge), log structured boot discovery.
- [ ] Code review có ≥ 1 approve từ owner module DF-MOD-08.
- [ ] Release notes / changelog cập nhật.
- [ ] Tài liệu troubleshooting cho trường hợp "extension không nạp" đã có.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-05, FR-08-06).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — mục 4.2.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Platform Engineer, Automation Builder.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Platform profile, Step type.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
