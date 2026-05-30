# DF-T-06-001 — Content type registry & platform-qualified validation

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-001 |
| **Title** | Content type registry & platform-qualified validation |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `layer:db`, `type:feature`, `platform:agnostic`, `persona:automation-builder`, `coverage:L2` |
| **Truy vết — FR refs** | FR-06-05 |
| **Truy vết — UC refs** | UC-06-04, UC-06-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Module DF-MOD-06 tuyên bố nguyên tắc: mọi content item phải mang `content_type` theo định dạng `<platform>_<object>` — tuyệt đối không chấp nhận tên generic như `post`, `comment`, `video`, `thread`. Hiện tại trong source vẫn còn template legacy lưu content với type generic; báo cáo theo platform vì thế bị lẫn, query phải case-by-case, và sang platform thứ năm sẽ vỡ trận. Ticket này dựng một registry trung tâm khai báo danh sách content type hợp lệ, version chính thức của nó, và gate validation cứng ở mọi ngõ ghi content (`save_extraction` step, endpoint extract trực tiếp, bulk import). Đây là ticket nền móng — mọi ticket khác trong Epic phụ thuộc nó để có một định nghĩa thống nhất "content type là cái gì".

Persona hưởng lợi trực tiếp: Social Data Operator (báo cáo platform-clean) và Automation Builder (lỗi rõ tại thời điểm khai báo, không phải lúc dispatch). Trong lộ trình, registry là điều kiện để DF-E-08 (Social Platform Extensions) đăng ký content type của platform mới mà không phải đụng vào DB schema.

Đọc nhanh cho dev: ticket này dựng registry content type platform-qualified. Không cho runtime tạo content type tùy ý; mọi đường ghi content phải validate qua registry và từ chối tên generic như `post`, `comment`, `video`.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** khai báo content type bằng tên platform-qualified (`fb_post`, `tiktok_video`, ...) và được hệ thống từ chối ngay tại thời điểm save nếu dùng tên generic
> **Để** không tích lũy dữ liệu legacy gây vỡ báo cáo cho Social Data Operator về sau

Persona phụ: Social Data Operator (tiêu thụ báo cáo platform-clean), Platform Engineer (đăng ký content type khi mở rộng platform mới).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI duy trì registry chứa danh sách content type hợp lệ, mỗi entry gồm `code` (`fb_post`), `platform` (`facebook`), `object_kind` (`post`), `status` (`active|deprecated|preview`), `parent_kinds[]`, mô tả ngắn — trace FR-06-05.
- Hệ thống PHẢI seed registry với 9 content type chuẩn: `fb_post`, `fb_comment`, `tiktok_video`, `tiktok_comment`, `threads_post`, `threads_comment`, `ig_media`, `ig_comment`, `ig_profile` — trace FR-06-05.
- Hệ thống PHẢI cung cấp hàm `validate_content_type(code)` trả về `(ok, reason)` — `ok=false` cho tên generic (`post`, `comment`, `video`, `thread`, `media`) hoặc tên không có trong registry.
- Hệ thống PHẢI expose endpoint `GET /api/content/types` trả danh sách content type cho frontend hiển thị dropdown và cho DF-E-08 lấy danh sách khi mở rộng platform.
- Hệ thống PHẢI cho phép admin thêm content type mới qua DB migration; runtime KHÔNG cho tạo content type tùy ý qua API ở giai đoạn này (đề phòng inflation tên kiểu lung tung).
- Hệ thống NÊN log mọi yêu cầu save với content type không hợp lệ kèm caller id để truy vết template legacy còn sót.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Save với platform-qualified type — luồng thành công**

```
Given content type registry đã seed 9 entry chuẩn
And caller có quyền write trong organization X
When caller gọi save_extraction với content_type = "fb_post" + payload hợp lệ
Then content_item được lưu thành công
And bản ghi có content_type = "fb_post" và platform = "facebook"
```

**AC-2: Validation từ chối generic name**

```
Given registry đã active
When caller gọi save_extraction với content_type = "post"
Then API trả lỗi 422 với error_code = "CONTENT_TYPE_GENERIC_REJECTED"
And error message liệt kê các candidate platform-qualified gần nhất (fb_post, tiktok_video, ...)
And không có bản ghi content_item nào được tạo
```

**AC-3: Validation từ chối content type không có trong registry**

```
Given registry chỉ có 9 entry chuẩn
When caller gọi save_extraction với content_type = "youtube_short"
Then API trả lỗi 422 với error_code = "CONTENT_TYPE_NOT_REGISTERED"
And log ghi nhận caller_id + scenario_id để truy vết
```

**AC-4: Endpoint list registry**

```
Given registry seed xong
When client gọi GET /api/content/types
Then trả 200 với danh sách 9 entry
And mỗi entry có code, platform, object_kind, status, parent_kinds, description
And phản hồi cache-able (header Cache-Control: max-age=300)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI admin thêm content type runtime — content type mới chỉ qua DB migration ở giai đoạn này (sẽ xem xét sau khi platform engineer có nhu cầu thực).
- KHÔNG bao gồm migration content legacy có type generic sang platform-qualified — đó là ticket vận hành tách riêng (sẽ tạo khi cần).
- KHÔNG bao gồm content type cho story Instagram (`ig_story`) — đặc tả module ghi rõ chưa nằm trong Draft hiện tại.
- KHÔNG bao gồm validation `parent_kinds` (cha-con) — sẽ xử lý ở DF-T-06-002 cùng với data model.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Định nghĩa interface `ContentTypeRegistry` với 4 method: `get(code)`, `list()`, `validate(code)`, `is_active(code)`.
- [ ] Implement in-memory loader đọc từ bảng `content_types` khi service khởi động và mỗi 5 phút.
- [ ] Tích hợp validate vào path save_extraction (placeholder cho DF-T-06-009) và endpoint extract trực tiếp.
- [ ] Tích hợp validate vào bulk import path (placeholder cho DF-T-06-009).

**Contract / API** (`layer:contract`)

- [ ] Đặc tả `GET /api/content/types` (response schema + ví dụ).
- [ ] Đặc tả error_code mới: `CONTENT_TYPE_GENERIC_REJECTED`, `CONTENT_TYPE_NOT_REGISTERED`, `CONTENT_TYPE_DEPRECATED`.
- [ ] Cập nhật OpenAPI spec.

**Database / Migration** (`layer:db`)

- [ ] Migration tạo bảng `content_types(code PK, platform, object_kind, status, parent_kinds_json, description, created_at, updated_at)`.
- [ ] Migration seed 9 entry chuẩn.
- [ ] Migration backfill: scan bảng `content_items`, đếm các content_type không match registry → đẩy vào báo cáo legacy (không sửa dữ liệu).

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/modules/06-content-extraction-artifacts.md` mục 6 FR-06-05 với link tới ticket.
- [ ] Viết section "How to add a new content type" trong `docs/modules/content.md`.
- [ ] Cập nhật changelog Epic.

**Test** (`layer:test`)

- [ ] Unit test cho `validate_content_type` (positive, negative, edge).
- [ ] Integration test endpoint `GET /api/content/types`.
- [ ] Integration test reject trên save_extraction (cần stub DF-T-06-009).

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-001-01 | Positive | Registry seed đủ 9 entry | Gọi `validate_content_type("fb_post")` | Trả `(ok=true, reason=None)` |
| TC-DF-T-06-001-02 | Positive | Registry seed đủ; client auth hợp lệ | `GET /api/content/types` | HTTP 200; body chứa 9 entry; có `fb_post`, `ig_profile` |
| TC-DF-T-06-001-03 | Negative | Registry seed đủ | Gọi `validate_content_type("post")` | Trả `(ok=false, reason="GENERIC")`; suggestion liệt kê 4 entry `*_post` |
| TC-DF-T-06-001-04 | Negative | Registry seed đủ | Gọi `validate_content_type("snap_story")` | Trả `(ok=false, reason="NOT_REGISTERED")`; log ghi attempt |
| TC-DF-T-06-001-05 | Edge | Registry rỗng (corruption sau migration fail) | Service khởi động, gọi `validate_content_type("fb_post")` | Service raise `RegistryNotInitialized` lúc bootstrap; healthcheck báo unhealthy; không bao giờ silent-accept |
| TC-DF-T-06-001-06 | Edge | Content type được mark `status=deprecated` | Caller save với content_type deprecated | Trả 422 `CONTENT_TYPE_DEPRECATED`; log warn ghi caller; gợi ý content type thay thế nếu có |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** Không (ticket nền móng).

**Chặn:** DF-T-06-002, DF-T-06-007, DF-T-06-008, DF-T-06-009.

**Phụ thuộc giữa Epic:** DF-E-08 (Social Platform Extensions) sẽ tiêu thụ registry này khi đăng ký content type cho platform mới — cần thống nhất naming convention `<platform>_<object>` trước khi DF-E-08 mở rộng.

**Rủi ro:**

- **Template scenario legacy lưu type generic:** sẽ gặp error 422 ngay khi deploy registry → giảm thiểu: chạy backfill scan trước, ra báo cáo template cần migrate, có flag `legacy_accept_for_org=<org_id>` cho phép tạm thời (mặc định false), gỡ flag sau 1 quý.
- **Cache 5 phút có thể delay sync khi thêm content type mới qua migration:** giảm thiểu: cung cấp endpoint admin `POST /api/content/types/refresh` để invalidate cache.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80% cho `ContentTypeRegistry`.
- [ ] Tất cả TC-DF-T-06-001-* map sang test tự động và pass.
- [ ] Migration seed 9 entry chuẩn chạy thành công trên staging và production.
- [ ] `docs/modules/content.md` mục registry đã cập nhật.
- [ ] `docs/official_docs/modules/06-content-extraction-artifacts.md` mục FR-06-05 link tới ticket.
- [ ] Telemetry: metric `content_type_validate_total{result=ok|generic|not_registered|deprecated}` đã có; log error có caller id.
- [ ] Code review ≥ 1 approve từ owner module Content.
- [ ] Release notes ghi nhận "Content type registry với 9 entry chuẩn".
- [ ] Báo cáo backfill liệt kê content_type generic trong DB hiện tại đã được gửi tới owner module.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §6 FR-06-05](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Ma trận năng lực:** [03-capability-matrix.md §4.2 "Content type platform-qualified"](../../official_docs/03-capability-matrix.md).
- **Platform profiles:** [facebook.md §3](../../official_docs/platforms/facebook.md), [tiktok.md §3](../../official_docs/platforms/tiktok.md), [threads.md §3](../../official_docs/platforms/threads.md), [instagram.md §3](../../official_docs/platforms/instagram.md).
- **Nhóm người dùng:** Automation Builder (§3.2), Social Data Operator (§3.1).
- **Thuật ngữ:** [Content type](../../official_docs/00-glossary.md), [Platform-qualified content type](../../official_docs/00-glossary.md).
