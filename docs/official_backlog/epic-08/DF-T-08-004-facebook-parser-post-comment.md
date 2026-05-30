# DF-T-08-004 — Facebook parser: post / comment / feed

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-004 |
| **Title** | Facebook parser — post / comment / feed với strategy `fb_posts` và `fb_comments` |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P0 |
| **Story Points** | 8 |
| **Status** | Ready |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:facebook`, `coverage:L2`, `persona:platform-engineer`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-08-02, FR-08-07, FR-08-08, FR-08-09, FR-08-12 |
| **Truy vết — UC refs** | UC-08-03, UC-08-05, UC-08-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Facebook là platform reference của Device Farm — nền tảng đầu tiên đạt L2 Active. Parser Facebook là **core artifact** của trạng thái Active đó: không có parser thì không có extraction strategy chạy được, không có content item `fb_post` / `fb_comment` lưu vào collection, không có giá trị nghiệp vụ cho Social Data Operator.

Ticket này hiện thực hóa parser cho hai strategy chính (`fb_posts`, `fb_comments`) và feed scroller. Parser nhận hierarchy snapshot + screenshot ref + scenario context, chuẩn hóa thành runtime object có schema cố định, map sang content_items với content type qualified `fb_post` / `fb_comment`, lưu các field platform-specific (reaction breakdown, sponsored flag, group id) vào `raw_data`. Quan hệ comment-reply biểu diễn qua `parent_id` + `item_level`.

Persona hưởng lợi chính: **Social Data Operator** (use case cốt lõi crawl post và comment ở quy mô), **Platform Engineer** (template parser cho TikTok / Threads / Instagram noi theo).

Đọc nhanh cho dev: ticket này là parser Facebook L2 Active cho `fb_posts` và `fb_comments`. Parser phải map field chung vào `content_items`, đưa field Facebook-specific vào `raw_data`, báo lỗi rõ khi UI mismatch và dùng dedupe key để tránh ghi trùng.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** scenario Facebook dùng strategy `fb_posts` và `fb_comments` để parse post và comment thành content item có cấu trúc nhất quán
> **Để** dữ liệu thu được có traceability đầy đủ, query được theo platform, và tái lập được cây comment qua parent_id

## 4. Yêu cầu chức năng

- Hệ thống PHẢI implement strategy `fb_posts` parse từ feed/group/page screen → list object `posts` — trace FR-08-02.
- Hệ thống PHẢI implement strategy `fb_comments` parse từ comment-list screen → list object `comments` có `parent_id` và `item_level` — trace FR-08-02, FR-08-08.
- Hệ thống PHẢI map field chung (text, author, author_id, permalink, like_count, comment_count, share_count, posted_at, media_urls) vào cột content_items chuẩn — trace FR-08-07.
- Hệ thống PHẢI lưu field platform-specific (reaction breakdown, sponsored flag, group id, feed source) vào `raw_data` JSON — trace FR-08-07.
- Hệ thống PHẢI khai báo dedupe key cho mỗi strategy (`fb_posts.dedupe_key = permalink`, `fb_comments.dedupe_key = comment_id + parent_id`) — trace FR-08-09.
- Hệ thống PHẢI báo lỗi rõ ràng khi hierarchy không khớp pattern Facebook (vd Facebook đã update UI) — không silent return list rỗng — trace FR-08-12.
- Hệ thống NÊN log số item parse được vs số item bỏ qua kèm reason để Platform Engineer debug.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Parse fb_posts từ feed screen**

```
Given device Android đã mở Facebook app ở news feed
And scenario chứa step extract strategy `fb_posts` với target collection `coll-A`
When scenario executor chạy tới step extract
Then parser nhận hierarchy + screenshot, parse ra ≥ 1 object post
And mỗi post có field: text, author, author_id, permalink, counter, posted_at
And mỗi post lưu thành content_item type `fb_post`, gắn collection `coll-A`
And field platform-specific (reaction breakdown) lưu vào `raw_data`
And dedupe key dùng `permalink` — chạy lại scenario không tạo duplicate
```

**AC-2: Parse fb_comments có parent_id và item_level**

```
Given device đã mở 1 post Facebook và đã tap mở comment list
And scenario chứa step extract strategy `fb_comments`
When parser chạy
Then parser trả về list comment với mỗi item có `parent_id` (id của post hoặc comment cha) và `item_level` (1 cho comment trực tiếp, 2 cho reply, ...)
And content_items lưu với content_type `fb_comment`, traceability tới post gốc qua parent_id
And query API có thể lấy lại cây thảo luận theo parent_id
```

**AC-3: Lỗi rõ ràng khi UI không khớp pattern**

```
Given device mở screen không phải Facebook (vd Settings)
When scenario chạy strategy `fb_posts`
Then parser raise mã lỗi `FB_PARSER_UI_MISMATCH`
And error message ghi "Expected fb feed selector pattern, got <actual>"
And không lưu content_item nào
And artifact (screenshot, hierarchy) đính kèm execution để debug
```

**AC-4: Dedupe key chống ghi trùng**

```
Given scenario A đã extract 100 post Facebook vào collection X
When scenario B chạy cùng group, cùng collection X
And 30 post overlap với scenario A
Then content_items chỉ có 100 + 70 = 170 bản ghi unique (không phải 200)
And dedupe dựa trên permalink
And log ghi "30 duplicate skipped"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm step action `fb_tap_comment_button` (mở context comment) — sẽ xử lý trong DF-T-08-005.
- KHÔNG bao gồm scrolling logic (parser nhận hierarchy đã ổn định) — scrolling là job của scenario step `swipe`.
- KHÔNG bao gồm parse video/reel — chỉ parse text post và media URL; video full parse là backlog Q3.
- KHÔNG bao gồm parse Facebook Stories — không trong scope L2 hiện tại.
- KHÔNG bao gồm OCR/AI vision fallback khi hierarchy thiếu — sẽ phối hợp DF-E-06 (Content Extraction).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `FacebookPostParser` (hierarchy → posts[])
- [ ] Implement `FacebookCommentParser` (hierarchy → comments[] với parent_id, item_level)
- [ ] Implement field mapping `posts[] → content_items` với raw_data
- [ ] Implement dedupe logic dựa permalink (posts) và comment_id (comments)
- [ ] Implement mã lỗi `FB_PARSER_UI_MISMATCH`
- [ ] Đăng ký vào registry qua contract DF-T-08-001

**Contract / API** (`layer:contract`)

- [ ] Schema runtime object `FacebookPost` và `FacebookComment`
- [ ] Schema content_items column mapping + raw_data JSON shape

**Database / Migration** (`layer:db`)

- [ ] Verify cột `content_items.content_type` chấp nhận `fb_post`, `fb_comment`
- [ ] Index trên (content_type, dedupe_key) cho performance dedup
- [ ] Index trên (content_type, parent_id) cho query cây thảo luận

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/platforms/facebook.md` mục 3 (phạm vi dữ liệu) nếu thêm field mới
- [ ] Tutorial "Crawl Facebook post" cho Social Data Operator
- [ ] Liệt kê tất cả field map vào content_items vs raw_data

**Test** (`layer:test`)

- [ ] Unit test parser với 10 sample hierarchy snapshot (real captures)
- [ ] Test edge: hierarchy thiếu field, hierarchy có sponsored post, hierarchy có reaction breakdown
- [ ] Test dedupe: chạy 2 lần cùng dataset
- [ ] Integration test full path: scenario → executor → parser → save_extraction → query

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-004-01 | Positive | Hierarchy snapshot real của feed FB với 5 post | Parser chạy strategy `fb_posts` | Trả về 5 post với đủ field; content_items lưu 5 bản với content_type `fb_post`; raw_data chứa reaction breakdown |
| TC-DF-T-08-004-02 | Positive | Hierarchy snapshot comment list với 3 comment cấp 1, 2 reply | Parser chạy strategy `fb_comments` | Trả về 5 comment; 3 có item_level=1, 2 có item_level=2 và parent_id trỏ về comment cấp 1; query cây thảo luận đúng cấu trúc |
| TC-DF-T-08-004-03 | Negative | Hierarchy của screen Settings (không phải FB feed) | Parser chạy strategy `fb_posts` | Raise `FB_PARSER_UI_MISMATCH`; không lưu content_item; artifact đính kèm |
| TC-DF-T-08-004-04 | Negative | Hierarchy malformed (XML không hợp lệ) | Parser chạy | Raise `FB_PARSER_INVALID_HIERARCHY`; log chi tiết; không crash executor |
| TC-DF-T-08-004-05 | Edge | Chạy strategy `fb_posts` 2 lần cùng collection với 30 post overlap | Đo unique count | content_items có (lần 1) + (lần 2 - overlap) bản; dedupe theo permalink hoạt động |
| TC-DF-T-08-004-06 | Edge | Comment cấp 3 (reply của reply) | Parser chạy | item_level=3; parent_id trỏ comment cấp 2; cây thảo luận tái lập đúng |
| TC-DF-T-08-004-07 | Edge | Post có sponsored flag và promotional metadata | Parser chạy | sponsored flag lưu trong raw_data; content_item vẫn được lưu (không skip); log info |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002.

**Chặn:** DF-T-08-005 (handler dùng parser khi extract sau action), DF-T-08-006 (scenario template).

**Phụ thuộc giữa Epic:**

- **DF-E-06 (Content & Extraction)** — `save_extraction` API và schema `content_items` là điểm parser ghi dữ liệu vào. Cần phối hợp định nghĩa `raw_data` JSON shape.

**Rủi ro:**

- **Facebook đổi UI thường xuyên** → giảm thiểu: 10 golden sample hierarchy được commit, regression test chạy hàng tuần, alert khi parser tỷ lệ thành công < 95%.
- **`raw_data` JSON shape không có schema → khó query sau** → giảm thiểu: document shape ở `docs/official_docs/platforms/facebook.md` mục 3, version field trong raw_data.
- **Dedupe key sai (permalink trùng cho group khác) → mất dữ liệu** → giảm thiểu: dedupe scope = collection, không cross-collection.

**Phụ thuộc bên ngoài:** Phụ thuộc app Facebook Android phiên bản tested (ghi rõ version trong scenario template).

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80% trên file parser.
- [ ] Tất cả TC-DF-T-08-004-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/facebook.md` cập nhật field map mới.
- [ ] Schema runtime object đã commit.
- [ ] 10 golden hierarchy sample đã commit làm fixture.
- [ ] Telemetry: metric `fb_parser_success_rate`, `fb_parser_items_parsed`.
- [ ] Code review ≥ 1 approve từ owner module DF-MOD-08 và DF-MOD-06.
- [ ] Đã chạy thử trên ≥ 5 thiết bị thật với 100 scenario thực tế, tỷ lệ thành công ≥ 95%.
- [ ] Release notes cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-02, FR-08-07, FR-08-08, FR-08-09).
- **Platform profile:** [facebook.md](../../official_docs/platforms/facebook.md) — mục 3 (Phạm vi dữ liệu), mục 5 (L2 Scenario automation).
- **Module Content:** [06-content-extraction-artifacts.md](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — mục 4.2 Facebook Active.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Social Data Operator, Platform Engineer.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Platform-qualified content type, raw_data, parent_id / item_level.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
