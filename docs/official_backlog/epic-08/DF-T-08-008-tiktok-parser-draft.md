# DF-T-08-008 — TikTok parser draft

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-008 |
| **Title** | TikTok parser draft — khung strategy `tiktok_videos` và `tiktok_comments` (Draft target) |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:tiktok`, `coverage:L2`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-02, FR-08-06, FR-08-07, FR-08-08, FR-08-09, FR-08-12 |
| **Truy vết — UC refs** | UC-08-01, UC-08-05, UC-08-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

TikTok hiện ở trạng thái **Draft target** — contract đã định nghĩa naming `tiktok_videos`, `tiktok_comments`, content type `tiktok_video`, `tiktok_comment`, nhưng parser chưa implement. Hệ quả: scenario social dùng tên `tiktok_*` đang chỉ là intent, runtime sẽ từ chối.

Ticket này tạo **khung parser TikTok** ở mức draft — implement đăng ký vào registry, parse được hierarchy snapshot đơn giản (1 video, vài comment), trả về object runtime đúng schema. Coverage KHÔNG hoàn chỉnh: chưa xử lý edge case (video carousel, live stream, music tag), chưa có dedupe robust, chưa có 10 golden sample như Facebook. Trạng thái Draft target nghĩa là Platform Engineer có thể tiếp tục mở rộng khi lộ trình đẩy TikTok sang Active (2-4 tuần engineering theo platform profile).

Persona hưởng lợi: **Platform Engineer** (có khung để mở rộng sau), **Social Data Operator pilot** (chạy thử workflow TikTok ở quy mô nhỏ trong giai đoạn pilot).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một khung parser TikTok draft đăng ký được vào registry và parse được hierarchy đơn giản
> **Để** khi lộ trình đẩy TikTok sang Active, có điểm khởi đầu thay vì build từ rỗng

## 4. Yêu cầu chức năng

- Hệ thống PHẢI implement `TikTokVideoParser` đăng ký strategy `tiktok_videos` — trace FR-08-02.
- Hệ thống PHẢI implement `TikTokCommentParser` đăng ký strategy `tiktok_comments` với `parent_id` và `item_level` — trace FR-08-02, FR-08-08.
- Hệ thống PHẢI map field chung (author, caption, view_count, like_count, comment_count, video_url, posted_at) vào content_items với content_type `tiktok_video` / `tiktok_comment` — trace FR-08-07.
- Hệ thống PHẢI lưu music_id, sound_track, hashtag_list vào `raw_data` — trace FR-08-07.
- Hệ thống PHẢI khai báo dedupe key: `tiktok_videos.dedupe_key = video_id`, `tiktok_comments.dedupe_key = comment_id` — trace FR-08-09.
- Hệ thống PHẢI báo lỗi rõ ràng khi hierarchy không khớp pattern TikTok — trace FR-08-12.
- Platform profile `docs/official_docs/platforms/tiktok.md` PHẢI cập nhật mục known gaps liệt kê edge case chưa hỗ trợ (carousel, live, music detail) — trace FR-08-06.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Parse 1 TikTok video cơ bản**

```
Given device mở TikTok feed với 1 video hiển thị
And scenario chứa step extract strategy `tiktok_videos`
When parser chạy
Then trả về 1 object video với field author, caption, view_count, video_url
And content_item lưu type `tiktok_video`, raw_data chứa music_id và hashtag_list
And dedupe key = video_id
```

**AC-2: Parse comment với parent_id**

```
Given device mở comment list của 1 video
When parser chạy strategy `tiktok_comments`
Then trả về list comment với parent_id (video_id hoặc comment_id cha) và item_level
And content_item type `tiktok_comment`, traceability tới video gốc
```

**AC-3: Báo lỗi khi UI không phải TikTok**

```
Given device mở screen khác (vd Settings)
When parser chạy strategy `tiktok_videos`
Then raise `TIKTOK_PARSER_UI_MISMATCH`
And artifact đính kèm execution
And profile platform note: "draft, edge case UI variation chưa cover"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm handler action (like, follow, comment) — sẽ xử lý trong DF-T-08-009.
- KHÔNG bao gồm parser carousel (multiple video trong 1 post), live stream, ad video — known gaps, sẽ xử lý khi chuyển Active.
- KHÔNG bao gồm 10 golden sample đầy đủ như Facebook — chỉ có 2-3 sample đại diện cho draft.
- KHÔNG bao gồm frontend node TikTok — sẽ ưu tiên khi chuyển Active.
- KHÔNG bao gồm scenario template — không trong draft scope.
- KHÔNG bao gồm L3 guardrail — Draft (preview).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `TikTokVideoParser`
- [ ] Implement `TikTokCommentParser` với parent_id
- [ ] Đăng ký 2 strategy vào registry
- [ ] Implement mã lỗi `TIKTOK_PARSER_UI_MISMATCH`

**Contract / API** (`layer:contract`)

- [ ] Schema runtime object `TikTokVideo`, `TikTokComment`

**Database / Migration** (`layer:db`)

- [ ] Verify content_items chấp nhận content_type `tiktok_video`, `tiktok_comment`

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/platforms/tiktok.md` mục 3 (phạm vi dữ liệu) và mục known gaps
- [ ] Ghi rõ trạng thái Draft target và completion criteria

**Test** (`layer:test`)

- [ ] Unit test với 2-3 hierarchy sample
- [ ] Integration test parser → save_extraction
- [ ] Test edge: hierarchy malformed

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-008-01 | Positive | Hierarchy TikTok feed 1 video | Parser chạy `tiktok_videos` | 1 object video; content_item type `tiktok_video`; raw_data có music_id |
| TC-DF-T-08-008-02 | Positive | Hierarchy comment list 3 comment, 1 reply | Parser chạy `tiktok_comments` | 4 comment; reply có item_level=2 và parent_id đúng |
| TC-DF-T-08-008-03 | Negative | Hierarchy screen Settings | Parser chạy | Raise `TIKTOK_PARSER_UI_MISMATCH`; artifact attach |
| TC-DF-T-08-008-04 | Negative | Hierarchy malformed | Parser chạy | Raise `TIKTOK_PARSER_INVALID_HIERARCHY`; không crash executor |
| TC-DF-T-08-008-05 | Edge | Hierarchy có carousel video (nhiều media) | Parser chạy | Parse video đầu, log warning "carousel not fully supported (draft)"; raw_data ghi flag carousel=true |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002.

**Chặn:** DF-T-08-009.

**Phụ thuộc giữa Epic:**

- **DF-E-06 (Content & Extraction)** — `save_extraction` API, schema content_items.

**Rủi ro:**

- **TikTok đổi UI nhanh hơn Facebook** → giảm thiểu: regression test ít nhất hàng tuần; mark draft và set expectation thấp.
- **Pilot user kỳ vọng TikTok hoạt động như Facebook** → giảm thiểu: doc rõ Draft target, frontend hiển thị badge "Draft" trên platform selector.

**Phụ thuộc bên ngoài:** TikTok Android app phiên bản tested (ghi rõ trong profile).

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 70% (lower bar cho draft so với 80% cho Active).
- [ ] Tất cả TC-DF-T-08-008-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/tiktok.md` cập nhật known gaps.
- [ ] Ma trận năng lực `03-capability-matrix.md` ghi parser status "Draft" cho TikTok.
- [ ] Telemetry: metric `tiktok_parser_success_rate`.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi rõ "TikTok parser draft — preview, not production-grade".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-02, FR-08-06).
- **Platform profile:** [tiktok.md](../../official_docs/platforms/tiktok.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — mục 4.2 TikTok Draft.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Platform Engineer.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md).
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — TikTok Active milestone.
