# DF-T-08-010 — Threads parser draft

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-010 |
| **Title** | Threads parser draft — khung strategy `threads_posts` và `threads_comments` (Draft target) |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:threads`, `coverage:L2`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-02, FR-08-06, FR-08-07, FR-08-08, FR-08-09, FR-08-12 |
| **Truy vết — UC refs** | UC-08-01, UC-08-05, UC-08-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Threads (Meta) đang ở trạng thái **Draft target**. Tương tự TikTok và Instagram, contract đã định nghĩa naming `threads_posts`, `threads_comments`, content type `threads_post`, `threads_comment`, nhưng parser chưa implement. Threads có lợi thế nhỏ là UI và cấu trúc post gần Twitter/X-style với thread reply, parent-child trong cùng feed — dễ map sang `parent_id` + `item_level`.

Ticket này tạo **khung parser Threads** ở mức draft: parse được 1 post và reply chain đơn giản, lưu hashtag, mention vào `raw_data`. Coverage chưa hoàn chỉnh: chưa xử lý quote-repost, chưa parse media attachment đa dạng, chưa có dedupe robust qua bridging post_id giữa Threads và Instagram (cùng Meta account).

Persona hưởng lợi: **Platform Engineer** (mở rộng khi lộ trình đẩy Threads Active).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một khung parser Threads draft đăng ký được vào registry và parse được hierarchy đơn giản
> **Để** khi lộ trình đẩy Threads sang Active, có điểm khởi đầu thay vì build từ rỗng

## 4. Yêu cầu chức năng

- Hệ thống PHẢI implement `ThreadsPostParser` đăng ký strategy `threads_posts` — trace FR-08-02.
- Hệ thống PHẢI implement `ThreadsCommentParser` đăng ký strategy `threads_comments` với `parent_id` và `item_level` — trace FR-08-02, FR-08-08.
- Hệ thống PHẢI map field chung (author, text, like_count, reply_count, repost_count, posted_at, permalink) vào content_items với content_type `threads_post` / `threads_comment` — trace FR-08-07.
- Hệ thống PHẢI lưu hashtag_list, mention_list, media_urls vào `raw_data` — trace FR-08-07.
- Hệ thống PHẢI khai báo dedupe key: `threads_posts.dedupe_key = post_id`, `threads_comments.dedupe_key = comment_id` — trace FR-08-09.
- Hệ thống PHẢI báo lỗi rõ ràng khi hierarchy không khớp pattern Threads — trace FR-08-12.
- Platform profile `docs/official_docs/platforms/threads.md` PHẢI cập nhật known gaps (quote-repost, media variation) — trace FR-08-06.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Parse 1 Threads post cơ bản**

```
Given device mở Threads feed với 1 post
And scenario chứa step extract strategy `threads_posts`
When parser chạy
Then trả về 1 object post với field author, text, like_count, reply_count, posted_at, permalink
And content_item lưu type `threads_post`, raw_data chứa hashtag_list và mention_list
And dedupe key = post_id
```

**AC-2: Parse reply chain với parent_id**

```
Given device mở 1 Threads post với 5 reply
When parser chạy strategy `threads_comments`
Then trả về 5 reply với parent_id (post_id hoặc comment_id cha) và item_level
And cây thảo luận tái lập đúng qua query API
```

**AC-3: Báo lỗi khi UI không phải Threads**

```
Given device mở screen Instagram (Threads dùng chung Meta UI, có thể nhầm)
When parser chạy strategy `threads_posts`
Then raise `THREADS_PARSER_UI_MISMATCH`
And error message phân biệt rõ Threads vs Instagram
And artifact đính kèm
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm handler action — sẽ xử lý trong DF-T-08-011.
- KHÔNG bao gồm parse quote-repost (Threads repost giữ original post) — known gaps.
- KHÔNG bao gồm parse media attachment đa dạng (carousel, video) — known gaps.
- KHÔNG bao gồm 10 golden sample như Facebook — chỉ 2-3 sample cho draft.
- KHÔNG bao gồm frontend node, scenario template.
- KHÔNG bao gồm L3 guardrail.
- KHÔNG bao gồm bridging post_id giữa Threads và Instagram.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `ThreadsPostParser`
- [ ] Implement `ThreadsCommentParser` với parent_id
- [ ] Đăng ký 2 strategy vào registry
- [ ] Implement mã lỗi `THREADS_PARSER_UI_MISMATCH`

**Contract / API** (`layer:contract`)

- [ ] Schema runtime object `ThreadsPost`, `ThreadsComment`

**Database / Migration** (`layer:db`)

- [ ] Verify content_items chấp nhận `threads_post`, `threads_comment`

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/platforms/threads.md` mục 3 và known gaps

**Test** (`layer:test`)

- [ ] Unit test với 2-3 hierarchy sample
- [ ] Integration test parser → save_extraction
- [ ] Test phân biệt Threads vs Instagram UI

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-010-01 | Positive | Hierarchy Threads feed 1 post | Parser chạy `threads_posts` | 1 object post; content_item type `threads_post`; raw_data có hashtag và mention |
| TC-DF-T-08-010-02 | Positive | Hierarchy post với 5 reply có nested | Parser chạy `threads_comments` | 5 reply, item_level đúng, parent_id chỉ về post hoặc reply cha |
| TC-DF-T-08-010-03 | Negative | Hierarchy Instagram (UI chung Meta) | Parser chạy `threads_posts` | Raise `THREADS_PARSER_UI_MISMATCH`; error chỉ rõ "looks like Instagram, not Threads" |
| TC-DF-T-08-010-04 | Negative | Hierarchy malformed | Parser chạy | Raise `THREADS_PARSER_INVALID_HIERARCHY`; không crash |
| TC-DF-T-08-010-05 | Edge | Post là quote-repost (chứa original post nested) | Parser chạy | Parse outer post; raw_data ghi flag `is_repost=true` và `original_post_ref`; log warning "quote-repost partial support (draft)" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002.

**Chặn:** DF-T-08-011.

**Phụ thuộc giữa Epic:**

- **DF-E-06 (Content & Extraction)** — `save_extraction` API và content_items schema.

**Rủi ro:**

- **Threads chia sẻ UI component với Instagram, dễ confuse parser** → giảm thiểu: identifier check (package name, top-level navigation) trước khi parse; test phân biệt rõ trong CI.
- **Quote-repost không parse đầy đủ làm dữ liệu thiếu** → giảm thiểu: doc rõ known gap, raw_data lưu reference để parse lại khi Active.

**Phụ thuộc bên ngoài:** Threads Android app phiên bản tested.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 70%.
- [ ] Tất cả TC-DF-T-08-010-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/threads.md` cập nhật.
- [ ] Ma trận năng lực ghi parser status "Draft" cho Threads.
- [ ] Telemetry: metric `threads_parser_success_rate`.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi rõ "Threads parser draft — preview".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6.
- **Platform profile:** [threads.md](../../official_docs/platforms/threads.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — Threads Draft.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md).
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
