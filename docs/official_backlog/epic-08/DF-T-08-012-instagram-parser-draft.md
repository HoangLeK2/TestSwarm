# DF-T-08-012 — Instagram parser draft

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-012 |
| **Title** | Instagram parser draft — khung strategy `ig_media` và `ig_comments` (Draft target) |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:instagram`, `coverage:L2`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-02, FR-08-06, FR-08-07, FR-08-08, FR-08-09, FR-08-12 |
| **Truy vết — UC refs** | UC-08-01, UC-08-05, UC-08-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Instagram đang ở trạng thái **Draft target**. Contract đã định nghĩa naming `ig_media`, `ig_comments`, `ig_profile`, content type `ig_media`, `ig_comment`, `ig_profile`. Parser chưa implement. Instagram có đặc thù: phạm vi content type rộng hơn (post ảnh, video, reel, story) — `ig_media` là content type chung cho cả ba loại media, phân biệt qua field `media_type` trong runtime object.

Ticket này tạo **khung parser Instagram** ở mức draft: parse được post ảnh đơn giản, parse comment cấp 1, lưu media_url, caption vào content_items, lưu hashtag, mention, location_id, music_id (cho reel) vào `raw_data`. Coverage chưa hoàn chỉnh — chưa parse story (Story endpoint khác), chưa parse carousel đầy đủ, chưa parse reel music tag chi tiết, chưa có dedupe robust qua media_id.

Persona hưởng lợi: **Platform Engineer** (template để mở rộng khi lộ trình đẩy Instagram Active).

Đọc nhanh cho dev: ticket này chỉ dựng parser Instagram ở trạng thái `Draft`, tập trung vào `ig_media` và `ig_comments` cơ bản. Không coi đây là release gate L2 Active; các gap story, carousel đầy đủ, reel music chi tiết và dedupe robust vẫn nằm ngoài phạm vi ticket này.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một khung parser Instagram draft đăng ký được vào registry và parse được post ảnh + comment đơn giản
> **Để** khi lộ trình đẩy Instagram sang Active, có điểm khởi đầu thay vì build từ rỗng

## 4. Yêu cầu chức năng

- Hệ thống PHẢI implement `InstagramMediaParser` đăng ký strategy `ig_media` (cover post ảnh, post video, reel — phân biệt qua `media_type`) — trace FR-08-02.
- Hệ thống PHẢI implement `InstagramCommentParser` đăng ký strategy `ig_comments` với `parent_id` và `item_level` — trace FR-08-02, FR-08-08.
- Hệ thống PHẢI map field chung (author, caption, like_count, comment_count, posted_at, permalink, media_url, media_type) vào content_items với content_type `ig_media` / `ig_comment` — trace FR-08-07.
- Hệ thống PHẢI lưu hashtag_list, mention_list, location_id, music_id, carousel_count vào `raw_data` — trace FR-08-07.
- Hệ thống PHẢI khai báo dedupe key: `ig_media.dedupe_key = media_id`, `ig_comments.dedupe_key = comment_id` — trace FR-08-09.
- Hệ thống PHẢI báo lỗi rõ ràng khi hierarchy không khớp pattern Instagram — trace FR-08-12.
- Platform profile `docs/official_docs/platforms/instagram.md` PHẢI cập nhật known gaps (story, carousel full parse, reel music chi tiết) — trace FR-08-06.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Parse 1 Instagram post cơ bản (ảnh)**

```
Given device mở Instagram feed với 1 post ảnh
And scenario chứa step extract strategy `ig_media`
When parser chạy
Then trả về 1 object media với field author, caption, like_count, posted_at, media_url, media_type="image"
And content_item lưu type `ig_media`, raw_data chứa hashtag và location_id (nếu có)
And dedupe key = media_id
```

**AC-2: Parse reel với media_type=reel**

```
Given device mở Instagram ở 1 reel
When parser chạy strategy `ig_media`
Then trả về object với media_type="reel"
And raw_data chứa music_id (nếu có)
And content_item lưu type `ig_media`
```

**AC-3: Parse comment với parent_id**

```
Given device mở comment list của 1 post
When parser chạy strategy `ig_comments`
Then trả về list comment với parent_id (media_id hoặc comment_id) và item_level
And content_item type `ig_comment`, traceability tới media gốc
```

**AC-4: Báo lỗi khi UI không phải Instagram**

```
Given device mở Threads (UI gần Instagram)
When parser chạy strategy `ig_media`
Then raise `IG_PARSER_UI_MISMATCH`
And error message phân biệt "looks like Threads, not Instagram"
And artifact đính kèm
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm handler action — sẽ xử lý trong DF-T-08-013.
- KHÔNG bao gồm parse Story (endpoint UI khác hoàn toàn) — known gap.
- KHÔNG bao gồm parse carousel đầy đủ (chỉ lấy media đầu, ghi flag carousel) — known gap.
- KHÔNG bao gồm parse `ig_profile` (chỉ post và comment trong scope draft này).
- KHÔNG bao gồm 10 golden sample — chỉ 2-3 sample đại diện.
- KHÔNG bao gồm frontend node, scenario template, L3 guardrail.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `InstagramMediaParser` (cover image/video/reel)
- [ ] Implement `InstagramCommentParser` với parent_id
- [ ] Logic phân biệt media_type qua hierarchy structure
- [ ] Đăng ký 2 strategy vào registry
- [ ] Implement mã lỗi `IG_PARSER_UI_MISMATCH`

**Contract / API** (`layer:contract`)

- [ ] Schema runtime object `InstagramMedia`, `InstagramComment`
- [ ] Enum `media_type`: image, video, reel, carousel

**Database / Migration** (`layer:db`)

- [ ] Verify content_items chấp nhận `ig_media`, `ig_comment`

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/platforms/instagram.md` mục 3 và known gaps

**Test** (`layer:test`)

- [ ] Unit test với 2-3 hierarchy sample (post ảnh, post video, reel)
- [ ] Integration test parser → save_extraction
- [ ] Test phân biệt Instagram vs Threads UI

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-012-01 | Positive | Hierarchy Instagram feed 1 post ảnh | Parser chạy `ig_media` | 1 object media_type=image; content_item type `ig_media`; raw_data có hashtag |
| TC-DF-T-08-012-02 | Positive | Hierarchy 1 reel | Parser chạy `ig_media` | media_type=reel; raw_data có music_id |
| TC-DF-T-08-012-03 | Negative | Hierarchy Threads (UI gần Instagram) | Parser chạy `ig_media` | Raise `IG_PARSER_UI_MISMATCH`; message phân biệt rõ |
| TC-DF-T-08-012-04 | Negative | Hierarchy malformed | Parser chạy | Raise `IG_PARSER_INVALID_HIERARCHY`; không crash |
| TC-DF-T-08-012-05 | Edge | Hierarchy carousel post (5 ảnh) | Parser chạy | Parse ảnh đầu; raw_data ghi carousel_count=5, flag `partial_support=true`; log warning |
| TC-DF-T-08-012-06 | Edge | Hierarchy Story screen | Parser chạy `ig_media` | Raise `IG_PARSER_UI_MISMATCH`; chỉ rõ "Story not supported in draft" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002.

**Chặn:** DF-T-08-013.

**Phụ thuộc giữa Epic:**

- **DF-E-06 (Content & Extraction)** — `save_extraction` API, content_items schema.

**Rủi ro:**

- **Instagram chia sẻ UI component với Threads, dễ confuse** → giảm thiểu: identifier check package name; test phân biệt CI.
- **Carousel partial support gây hiểu nhầm dữ liệu đầy đủ** → giảm thiểu: raw_data flag `partial_support=true` rõ ràng.
- **Instagram UI update thường xuyên trên Reel** → giảm thiểu: regression test hàng tuần.

**Phụ thuộc bên ngoài:** Instagram Android app phiên bản tested.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 70%.
- [ ] Tất cả TC-DF-T-08-012-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/instagram.md` cập nhật.
- [ ] Ma trận năng lực ghi parser status "Draft" cho Instagram.
- [ ] Telemetry: metric `ig_parser_success_rate`.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi rõ "Instagram parser draft — preview".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6.
- **Platform profile:** [instagram.md](../../official_docs/platforms/instagram.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — Instagram Draft.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md).
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
