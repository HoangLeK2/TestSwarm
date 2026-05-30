# DF-T-06-010 — Content deduplication theo external_id (collection-scoped)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-010 |
| **Title** | Content deduplication theo external_id (collection-scoped) |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:db`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2` |
| **Truy vết — FR refs** | FR-06-11 (Lộ trình dedup) |
| **Truy vết — UC refs** | UC-06-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục §8: "Dedup chưa được enforce ở server-side. Hiện tại việc tránh trùng lặp content item phụ thuộc client (scenario gọi extraction phải tự khai báo dedup key hoặc kiểm tra trước khi save)." Module ghi rõ Lộ trình: server-side dedup theo (collection, platform, external_id). KPI module: tỷ lệ content trùng trong collection < 2%.

Ticket này hiện thực hóa dedup MVP ở server-side: theo tổ hợp (collection_id, platform, external_id). Nếu strategy không trả `external_id` thì content vẫn được lưu (không enforce); nhưng nếu có thì server-side block ngay tại insert.

Persona hưởng lợi: Social Data Operator (báo cáo không thổi số liệu).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** server tự từ chối content trùng theo external_id trong cùng collection
> **Để** không phải dọn dữ liệu trùng thủ công khi cùng 1 post được crawl bởi 2 scenario khác nhau

Persona phụ: Automation Builder (không phải tự xử dedup ở scenario logic phức tạp).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI enforce unique constraint trên tổ hợp `(organization_id, collection_id, platform, external_id)` cho content_items khi `external_id` non-null — trace FR-06-11 (Lộ trình dedup).
- Khi vi phạm unique, hệ thống KHÔNG raise exception cho caller mặc định — thay vào đó: trả về content_item_id của bản ghi hiện có, kèm flag `dedup_hit=true`.
- Hệ thống PHẢI cho phép caller (save_extraction step) chọn behavior:
  - `dedup_action="skip"` (mặc định): trả existing id, không update.
  - `dedup_action="update"`: cập nhật field thay đổi (counters, updated_at), giữ external_id.
  - `dedup_action="error"`: raise lỗi 409 (cho debugging).
- Hệ thống PHẢI cho phép content không có external_id được lưu nhiều lần (không dedup) — log warning để Automation Builder biết.
- Hệ thống PHẢI cung cấp endpoint `GET /api/content/collections/{id}/dedup-report` báo cáo tỷ lệ dedup hit gần đây.
- Hệ thống PHẢI có script `scripts/audit-content-duplicates.py` quét DB tìm trùng (cho legacy data chưa qua dedup).
- Hệ thống NÊN expose metric `content_dedup_hit_total{collection_id, platform, action}` cho dashboard.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Insert post trùng với dedup_action=skip**

```
Given collection C đã có content fb_post với external_id="story_123"
When save_extraction lưu post mới có external_id="story_123" + dedup_action=skip
Then không có content_item mới được tạo
And response trả existing content_item_id, dedup_hit=true
And metric content_dedup_hit_total tăng 1
```

**AC-2: dedup_action=update cập nhật counter**

```
Given existing fb_post có counters.likes=10
When save_extraction lưu lại với likes=42, dedup_action=update
Then content_item.counters.likes=42 và updated_at thay đổi
And external_id, posted_at giữ nguyên
And history audit ghi nhận update
```

**AC-3: Content không có external_id**

```
Given save_extraction lưu fb_comment không có external_id (UI không expose)
When insert
Then content_item được tạo bình thường (không dedup)
And warning log "content_without_external_id" với collection_id
```

**AC-4: Collection khác → không dedup cross-collection**

```
Given external_id="story_123" đã tồn tại trong collection C1
When save_extraction lưu cùng external_id vào collection C2
Then content_item mới được tạo trong C2 (vì dedup scope là collection)
And không có dedup hit
```

**AC-5: Dedup report**

```
Given collection C có 1000 insert, 50 dedup hit trong tuần qua
When GET /api/content/collections/{C.id}/dedup-report
Then trả {total_inserts:1000, dedup_hits:50, hit_rate:5%, by_platform:{...}, by_action:{skip:48, update:2}}
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm dedup cross-collection — đặc tả module ghi rõ scope collection.
- KHÔNG bao gồm fuzzy dedup (giống text content nhưng external_id khác) — không trong scope.
- KHÔNG bao gồm dedup theo content hash (hash text_content + author) — không trong scope.
- KHÔNG bao gồm migration data cũ có trùng — đó là vận hành tách riêng.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Service `DedupService.check_and_insert(content_data, dedup_action)` áp unique check trước insert.
- [ ] Tích hợp vào save_extraction step (DF-T-06-009) sau normalize step.
- [ ] Báo cáo dedup endpoint.
- [ ] Script audit cho legacy data.

**Contract / API** (`layer:contract`)

- [ ] Mở rộng schema save_extraction step thêm field `dedup_action`.
- [ ] OpenAPI endpoint dedup-report.
- [ ] Mã lỗi 409 `CONTENT_DUPLICATE_REJECTED` cho dedup_action=error.

**Database / Migration** (`layer:db`)

- [ ] Migration thêm partial unique index `UNIQUE (organization_id, collection_id, platform, external_id) WHERE external_id IS NOT NULL`.
- [ ] Migration backfill: nếu DB hiện có trùng, output báo cáo và yêu cầu vận hành xử lý trước khi enable constraint.

**Documentation** (`layer:docs`)

- [ ] Phần "Dedup behavior" trong `docs/modules/content.md`.
- [ ] Hướng dẫn Automation Builder chọn dedup_action.

**Test** (`layer:test`)

- [ ] Unit test 3 dedup_action.
- [ ] Test cross-collection.
- [ ] Test concurrency (2 insert song song cùng external_id).

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-010-01 | Positive | Collection C có "story_123" | save_extraction "story_123" lần 2, dedup_action=skip | Existing id trả về; dedup_hit=true; metric tăng |
| TC-DF-T-06-010-02 | Positive | Collection C có post likes=10 | save_extraction lần 2 likes=42, dedup_action=update | content_item updated likes=42 |
| TC-DF-T-06-010-03 | Negative | Không có external_id trong result | save_extraction lưu | Insert OK; warning log |
| TC-DF-T-06-010-04 | Negative | dedup_action=error, trùng | save_extraction lưu | 409 CONTENT_DUPLICATE_REJECTED |
| TC-DF-T-06-010-05 | Edge | 2 worker insert song song cùng (C, fb_post, story_X) | Race test | Chỉ 1 row insert; 1 row dedup_hit (DB constraint thắng) |
| TC-DF-T-06-010-06 | Edge | Migration backfill trên DB có 1000 trùng | Chạy backfill script | Báo cáo 1000 trùng; constraint chưa enable; instruction để vận hành |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-002 (cần cột external_id), DF-T-06-008 (collection), DF-T-06-009 (save step để tích hợp).

**Chặn:** Không có ticket downstream.

**Phụ thuộc giữa Epic:** Không.

**Rủi ro:**

- **DB hiện có trùng → bật unique constraint vỡ migration:** giảm thiểu: backfill report trước, vận hành dọn trước, enable constraint sau.
- **Strategy không trả external_id sẽ thoát dedup:** giảm thiểu: tài liệu khuyến nghị strategy có external_id; metric `content_without_external_id_total` để tracking.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Unit + integration test pass.
- [ ] Migration backfill báo cáo đã chạy trên staging.
- [ ] Unique index enable trên staging và production.
- [ ] Tài liệu "Dedup behavior" published.
- [ ] Telemetry: `content_dedup_hit_total`, `content_dedup_skipped_total` (vì thiếu external_id).
- [ ] Code review ≥ 1 approve.
- [ ] Changelog ghi nhận server-side dedup MVP.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §8 "Dedup chưa được enforce ở server-side"](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Đặc tả module KPI:** Tỷ lệ content item trùng trong cùng collection < 2%.
- **Nhóm người dùng:** Social Data Operator (§3.1).
- **Thuật ngữ:** [Content item](../../official_docs/00-glossary.md), [Content collection](../../official_docs/00-glossary.md).
