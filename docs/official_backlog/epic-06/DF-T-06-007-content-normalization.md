# DF-T-06-007 — Content normalization per type (fb / tiktok / threads / ig)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-007 |
| **Title** | Content normalization per type (fb / tiktok / threads / ig) |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `type:feature`, `platform:facebook`, `platform:tiktok`, `platform:threads`, `platform:instagram`, `persona:automation-builder`, `coverage:L2` |
| **Truy vết — FR refs** | FR-06-04, FR-06-05, FR-06-06 |
| **Truy vết — UC refs** | UC-06-04, UC-06-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module yêu cầu output của 3 engine (hierarchy, OCR, AI vision) đi qua **một** normalizer chung — cùng một bài Facebook trích từ hierarchy hay từ AI vision đều cho ra content item với cùng tập cột chuẩn; chênh lệch chỉ nằm trong `raw_data`. Đây là điểm cốt lõi đảm bảo Social Data Operator có thể query xuyên engine mà không phải biết bài này được extract bằng cách nào.

Normalizer hoạt động per content type — `fb_post` có rule riêng, `tiktok_video` có rule riêng, `ig_profile` có rule riêng. Ticket này dựng kiến trúc normalizer (interface + dispatcher) và implement 9 normalizer cụ thể tương ứng 9 content type chuẩn.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** mọi output extraction được đưa qua normalizer trước khi save, để mọi content_item cùng platform có cùng tập cột chuẩn
> **Để** Social Data Operator query và báo cáo đồng nhất, không phải lo engine nào tạo ra dữ liệu

Persona phụ: Social Data Operator (tiêu thụ dữ liệu chuẩn hóa).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp interface `Normalizer.normalize(engine_output, content_type, hint_config) -> NormalizedContent`.
- `NormalizedContent` PHẢI có: cột chuẩn (text_content, author_id, author_name, counters, posted_at, permalink, media_urls, ...) + `raw_data` (mọi field còn lại).
- Hệ thống PHẢI implement 9 normalizer: `FbPostNormalizer`, `FbCommentNormalizer`, `TiktokVideoNormalizer`, `TiktokCommentNormalizer`, `ThreadsPostNormalizer`, `ThreadsCommentNormalizer`, `IgMediaNormalizer`, `IgCommentNormalizer`, `IgProfileNormalizer` — trace FR-06-04, FR-06-05.
- Hệ thống PHẢI giữ mọi field không khớp cột chuẩn vào `raw_data` — KHÔNG strip — trace FR-06-06.
- Hệ thống PHẢI cho cùng input từ 2 engine khác nhau cho ra output cùng cột chuẩn (chỉ khác raw_data).
- Hệ thống PHẢI raise `NormalizationError` nếu input thiếu field bắt buộc của content type đó (ví dụ fb_post thiếu cả `text_content` lẫn `media_urls` → không có nội dung gì).
- Hệ thống PHẢI parse `posted_at` về ISO 8601 UTC từ các format platform khác nhau ("2 giờ trước", "Yesterday at 5 PM", timestamp Unix).
- Hệ thống PHẢI normalize counter (like, comment, share) từ string "1.2K" → integer 1200.
- Hệ thống NÊN log mọi field đẩy vào raw_data với key đầu mỗi platform để Platform Engineer biết gì đang chưa được map.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Same post qua hierarchy và AI vision cho output chuẩn giống nhau**

```
Given screenshot post Facebook đã biết ground truth (author "Nam Nguyễn", text "Hello", likes 42)
And cả hierarchy strategy fb_posts (mock) và AI vision đều extract được
When normalizer chạy cho cả 2 output
Then cả 2 NormalizedContent có cùng:
  - author_name = "Nam Nguyễn"
  - text_content = "Hello"
  - counters.likes = 42
  - content_type = "fb_post"
And raw_data có thể khác (hierarchy có resource_id, AI vision có confidence score)
```

**AC-2: Parse "1.2K" → 1200**

```
Given engine_output.counters.likes = "1.2K" (string)
When normalize content_type = fb_post
Then NormalizedContent.counters.likes = 1200 (int)
And tương tự "3.5M" → 3500000, "999" → 999
```

**AC-3: Field không khớp cột chuẩn đi vào raw_data**

```
Given engine_output có field "fb_internal_story_id" = "abc123" không map cột chuẩn
When normalize fb_post
Then NormalizedContent.raw_data["fb_internal_story_id"] = "abc123"
And không có thông tin nào bị bỏ qua silent
```

**AC-4: ig_profile có schema khác fb_post**

```
Given engine_output cho ig_profile có {username, follower_count, following_count, bio, is_verified}
When normalize ig_profile
Then NormalizedContent có các trường tương ứng (không có text_content, counters.likes của post)
And follower_count parse từ "1.5M" → 1500000
```

**AC-5: Thiếu field bắt buộc**

```
Given engine_output cho fb_post nhưng không có text_content cũng không có media_urls cũng không có permalink
When normalize
Then raise NormalizationError(missing=["text_or_media_required", "permalink"])
And không có content_item nào được tạo
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm strategy engine cụ thể (đó là DF-T-06-006 + DF-E-08).
- KHÔNG bao gồm save vào DB (đó là DF-T-06-009).
- KHÔNG bao gồm dedup (đó là DF-T-06-010).
- KHÔNG bao gồm content type `ig_story` (chưa trong Draft).
- KHÔNG bao gồm transform raw_data sang PII-scrubbed (câu hỏi mở đặc tả module).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Interface `Normalizer`, base class `BaseNormalizer` với util counter parse + date parse + URL normalize.
- [ ] 9 normalizer cụ thể.
- [ ] Dispatcher `NormalizationService.normalize(engine_output, content_type, hint_config)` route theo content_type.
- [ ] Lib `dateparser` cho posted_at multi-locale.
- [ ] Util parse counter "1.2K"/"1,234"/"千" thành int.

**Contract / API** (`layer:contract`)

- [ ] Schema `NormalizedContent` per content_type (9 schema).
- [ ] Mã lỗi `NormalizationError`, `MissingRequiredField`.
- [ ] Tài liệu mapping field nào về cột chuẩn, field nào về raw_data.

**Documentation** (`layer:docs`)

- [ ] Bảng "Field mapping per content type" trong `docs/modules/content.md`.
- [ ] Hướng dẫn Platform Engineer khi thêm content type mới: cần normalizer kèm.

**Test** (`layer:test`)

- [ ] Unit test cho từng normalizer với 5 fixture mỗi loại.
- [ ] Property test: input 2 engine → output cột chuẩn giống.
- [ ] Test parse counter, parse date với 20 case (tiếng Việt, tiếng Anh, tiếng Tây Ban Nha).

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-007-01 | Positive | Fixture fb_post hierarchy có 15 field | Normalize fb_post | NormalizedContent có 8 cột chuẩn + 7 field còn lại trong raw_data |
| TC-DF-T-06-007-02 | Positive | Cùng input qua hierarchy và AI vision (mock identical data) | Normalize cả 2 | Output cột chuẩn identical; raw_data khác |
| TC-DF-T-06-007-03 | Negative | fb_post thiếu cả text_content, media_urls, permalink | Normalize | `NormalizationError(missing_required)`; log đầy đủ |
| TC-DF-T-06-007-04 | Negative | Content type "post" (generic) | Normalize | `NormalizationError(unsupported_type)`; gợi ý content type platform-qualified |
| TC-DF-T-06-007-05 | Edge | Posted_at = "2 giờ trước" (tiếng Việt relative time) | Normalize fb_post | posted_at = (now - 2h) ISO 8601 UTC; tolerance ± 5 phút |
| TC-DF-T-06-007-06 | Edge | counters.likes = null (UI không hiển thị) | Normalize | counters.likes = null (không default 0); raw_data ghi "likes_field_missing" |
| TC-DF-T-06-007-07 | Edge | raw_data chứa 50 nested key | Normalize | Giữ nguyên struct; không strip; size check OK |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-001 (registry), DF-T-06-002 (data model), DF-T-06-004 (OCR), DF-T-06-005 (AI vision), DF-T-06-006 (Hierarchy).

**Chặn:** DF-T-06-009.

**Phụ thuộc giữa Epic:** DF-E-08 sẽ cung cấp ground truth field mapping cho mỗi platform. Cần đồng bộ field name với DF-E-08 trước khi freeze schema NormalizedContent.

**Rủi ro:**

- **Counter parse sai locale (tiếng Việt dùng "," là phân tách hàng nghìn; tiếng Anh dùng "."):** giảm thiểu: detect locale từ device locale hint hoặc content language.
- **Date parser fail trên format mới của platform:** giảm thiểu: fallback giữ raw string, ghi raw_data; alert nếu fail rate > 1%.

**Phụ thuộc bên ngoài:** lib `dateparser`.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] 9 normalizer hoàn thiện với fixture test.
- [ ] Property test "2 engine → same standard output" pass.
- [ ] Bảng field mapping per content type đã viết trong docs.
- [ ] Telemetry: `normalize_error_total{content_type, reason}`, `normalize_raw_data_keys_total{platform, key}`.
- [ ] Code review ≥ 1 approve owner module + 1 approve từ DF-E-08 owner.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §6 FR-06-04, FR-06-05, FR-06-06](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Platform profiles:** [facebook.md §3](../../official_docs/platforms/facebook.md), [tiktok.md §3](../../official_docs/platforms/tiktok.md), [threads.md §3](../../official_docs/platforms/threads.md), [instagram.md §3](../../official_docs/platforms/instagram.md).
- **Nhóm người dùng:** Automation Builder (§3.2), Social Data Operator (§3.1).
- **Thuật ngữ:** [Content type](../../official_docs/00-glossary.md), [raw_data](../../official_docs/00-glossary.md).
