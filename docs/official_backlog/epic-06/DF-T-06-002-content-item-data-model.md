# DF-T-06-002 — Content item & artifact data model (parent_id, item_level, traceability, raw_data)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-002 |
| **Title** | Content item & artifact data model (parent_id, item_level, traceability, raw_data) |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2` |
| **Truy vết — FR refs** | FR-06-05, FR-06-06, FR-06-07, FR-06-12, FR-06-13 |
| **Truy vết — UC refs** | UC-06-05, UC-06-06, UC-06-09, UC-06-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Một content item không sống cô lập — nó là điểm giao của 5 thực thể nghiệp vụ (collection, campaign, scenario, execution, device, account). Hôm nay, schema cũ thiếu trường traceability hoặc có nhưng nullable không enforce, dẫn tới hiện tượng "content mồ côi" mà Social Data Operator không trả lời được cho khách hàng "bài này lấy ở đâu". Đồng thời, đặc tả module yêu cầu mô hình comment-reply qua `parent_id` + `item_level` thay vì model riêng cho từng platform; raw_data dùng JSON để giữ trường platform-specific. Artifact (screenshot + hierarchy snapshot) là dòng dữ liệu song song lưu trên MinIO/S3, có liên kết execution + step index.

Ticket này dựng data model chính cho cả Epic — bảng `content_items`, bảng `content_collections`, bảng `execution_artifacts`, kèm index và constraint. Sau ticket này, mọi ticket khác (engine, normalizer, save_extraction, query) đều có chỗ ghi và chỗ đọc.

Đọc nhanh cho dev: ticket này là data model nền cho `content item` và `artifact`. Cần ưu tiên đúng `organization_id`, parent-child bằng `parent_id/item_level`, traceability tới campaign/scenario/execution/device/account, giữ nguyên `raw_data` và constraint/index phục vụ query sau này.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** mỗi content item lưu được đầy đủ context (campaign / scenario / execution / device / account, parent_id, item_level, raw_data) và artifact đính kèm execution
> **Để** mở một bài hay một comment thì biết ngay lấy từ đâu, ai thực hiện, và có evidence kèm

Persona phụ: Automation Builder (định nghĩa raw_data khi gặp trường platform-specific), Fleet Operator (mở artifact để debug device fail).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI lưu content_item với các cột chuẩn: `id`, `organization_id`, `collection_id`, `content_type` (FK registry — DF-T-06-001), `platform`, `external_id`, `author_id`, `author_name`, `text_content`, `permalink`, `media_urls_json`, `counters_json`, `posted_at`, `extracted_at`, `parent_id`, `item_level`, `raw_data` (JSONB), `campaign_id`, `scenario_id`, `execution_id`, `device_id`, `account_id`, `created_at`, `updated_at` — trace FR-06-05, FR-06-06, FR-06-13.
- Hệ thống PHẢI enforce `content_type` thuộc registry hợp lệ (DF-T-06-001).
- Hệ thống PHẢI cho `parent_id` nullable (root content = null); khi non-null phải trỏ tới content_item cùng `organization_id` — trace FR-06-07.
- Hệ thống PHẢI tính `item_level` = 1 + (parent.item_level nếu có, ngược lại 0); enforce qua trigger hoặc service layer — trace FR-06-07.
- Hệ thống PHẢI giữ `raw_data` nguyên vẹn, không strip field — kích thước tối đa 1 MB / item (báo lỗi nếu vượt) — trace FR-06-06.
- Hệ thống PHẢI lưu bảng `execution_artifacts(id, execution_id, step_index, kind ∈ {screenshot_pre, screenshot_post, hierarchy_snapshot, log}, object_key, content_type_mime, size_bytes, sha256, captured_at, retention_class)` — trace FR-06-12.
- Hệ thống PHẢI có index trên (collection_id, content_type, extracted_at), (campaign_id, extracted_at), (execution_id, step_index), (parent_id), (organization_id, platform, external_id).
- Hệ thống PHẢI enforce filter `organization_id` ở mọi query để tránh cross-tenant leak.
- Hệ thống NÊN soft-delete content_item (giữ row, set `deleted_at`) thay vì hard-delete để truy vết audit về sau.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Lưu post + comment với parent-child**

```
Given collection C tồn tại trong org X
And content type "fb_post" và "fb_comment" active trong registry
When Service tạo content_item P (type fb_post, parent_id null) sau đó content_item R (type fb_comment, parent_id = P.id)
Then P được lưu với item_level = 1
And R được lưu với item_level = 2 và parent_id = P.id
And query "lấy cây hội thoại dưới P" trả về cả P và R đúng thứ tự
```

**AC-2: Traceability đầy đủ**

```
Given content_item I được tạo từ execution E của campaign C, scenario S, trên device D, với account A
When client gọi GET /api/content/items/{I.id}
Then response chứa campaign_id, scenario_id, execution_id, device_id, account_id đúng giá trị
And nếu một id thiếu (extract trực tiếp ngoài campaign), trả về null với cờ `is_direct_extract = true`
```

**AC-3: raw_data preservation**

```
Given strategy fb_posts thu được payload có 25 trường, trong đó 8 trường không map vào cột chuẩn
When normalizer ghi content_item
Then 17 trường chuẩn nằm trong cột content_items
And 8 trường còn lại nằm nguyên trong raw_data JSON
And byte-by-byte raw_data == JSON đã được tạo (không strip, không reorder semantic)
```

**AC-4: Cross-tenant isolation**

```
Given content_item I thuộc org X
When user U thuộc org Y gọi GET /api/content/items/{I.id}
Then API trả 404 (không leak existence)
And audit log ghi attempt cross-tenant
```

**AC-5: Artifact đính kèm execution**

```
Given execution E có 20 step
When mỗi step kích hoạt pre/post capture
Then bảng execution_artifacts có 40 row liên kết E (kind screenshot_pre và screenshot_post), kèm sha256, size_bytes
And query GET /api/executions/{E.id}/artifacts trả 40 entry phân trang
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm logic gọi engine extraction — đó là DF-T-06-004/005/006.
- KHÔNG bao gồm normalizer — đó là DF-T-06-007.
- KHÔNG bao gồm `save_extraction` step và endpoint trực tiếp — đó là DF-T-06-009.
- KHÔNG bao gồm signed URL artifact preview — đó là DF-T-06-012.
- KHÔNG bao gồm retention/lifecycle policy — đó là DF-T-06-011.
- KHÔNG bao gồm server-side dedup — đó là DF-T-06-010.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Model ORM `ContentItem`, `ContentCollection`, `ExecutionArtifact`.
- [ ] Service `ContentItemRepository` (create, get, list, soft_delete) có organization filter mặc định.
- [ ] Validate `content_type` qua registry trước khi insert.
- [ ] Tính `item_level` ở service layer khi parent_id được set.
- [ ] Validate `raw_data` size ≤ 1 MB.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả schema response `content_item` (gồm trace ids).
- [ ] Đặc tả schema `execution_artifact` (không bao gồm object_key cho client thường — sẽ trả signed URL ở DF-T-06-012).
- [ ] Cập nhật OpenAPI.

**Database / Migration** (`layer:db`)

- [ ] Migration tạo bảng `content_collections(id, organization_id, owner_id, name, description, project_tag, created_at, deleted_at)`.
- [ ] Migration tạo bảng `content_items` với toàn bộ cột mục §4.
- [ ] Migration tạo bảng `execution_artifacts`.
- [ ] Tạo các index như §4.
- [ ] Foreign key constraint `content_items.parent_id` self-reference với `ON DELETE SET NULL`.
- [ ] FK `content_items.collection_id`, `content_items.campaign_id`, `content_items.scenario_id`, `content_items.execution_id`, `content_items.device_id`, `content_items.account_id` đều nullable cho `is_direct_extract`.
- [ ] Constraint check `item_level >= 1`.

**Infra / DevOps** (`layer:infra`)

- [ ] Cấu hình MinIO bucket `df-artifacts-{env}` với lifecycle rule placeholder (chi tiết ở DF-T-06-011).
- [ ] Secret credential MinIO inject qua env runtime.

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/modules/content.md` với ERD và mô tả từng cột.
- [ ] Cập nhật `docs/official_docs/modules/06-content-extraction-artifacts.md` mục 5.3 (ERD).
- [ ] Viết runbook "Soft-delete và recovery content".

**Test** (`layer:test`)

- [ ] Unit test repository (create, parent-child, item_level calc, cross-tenant).
- [ ] Integration test với DB thật (test container).
- [ ] Stress test 100k content items / org để check index hiệu quả.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-002-01 | Positive | Org X có collection C; registry đủ | Tạo content_item type fb_post với đầy đủ trace ids | Bản ghi tồn tại; item_level = 1; toàn bộ trace ids non-null |
| TC-DF-T-06-002-02 | Positive | Post P đã tồn tại | Tạo comment với parent_id = P.id | Comment có item_level = 2; query cây con dưới P trả P + comment |
| TC-DF-T-06-002-03 | Negative | Registry chỉ có 9 entry chuẩn | Tạo content_item với content_type = "snap_story" | Insert reject với FK violation hoặc validation 422 |
| TC-DF-T-06-002-04 | Negative | User U thuộc org Y | GET /api/content/items/{I.id} (I thuộc org X) | HTTP 404; audit log "cross_tenant_attempt" |
| TC-DF-T-06-002-05 | Edge | raw_data = JSON 2 MB | Tạo content_item với raw_data đó | Reject 422 `RAW_DATA_SIZE_EXCEEDED`; không có row được insert |
| TC-DF-T-06-002-06 | Edge | Parent cha bị soft-delete sau khi child tạo | Query cây con dưới parent | Vẫn trả về child với parent thông tin null hoặc tombstone; không crash |
| TC-DF-T-06-002-07 | Edge | Insert 50k content_item song song trong 1 collection | Stress test query với filter | Latency p95 < 3 s cho top 1000 record (KPI module) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-001 (cần registry để FK content_type).

**Chặn:** DF-T-06-007, DF-T-06-008, DF-T-06-009, DF-T-06-010, DF-T-06-011, DF-T-06-012.

**Phụ thuộc giữa Epic:** DF-E-02 cung cấp định danh `device_id`; DF-E-04 cung cấp `campaign_id`, `scenario_id`, `execution_id`; DF-E-07 cung cấp `account_id`. Cần thống nhất id format trước khi seed.

**Rủi ro:**

- **JSONB index trên raw_data ngốn dung lượng:** giảm thiểu: không tạo GIN index toàn bộ raw_data; chỉ index cho key cố định nếu cần (sẽ quyết định ở DF-T-06-008).
- **Self-referential parent_id có thể gây cycle:** giảm thiểu: validate ở service layer "ancestor không chứa self"; thêm depth cap = 10 cho item_level.
- **Migration trên DB production có nhiều dòng:** giảm thiểu: chia migration làm 3 phase (add column nullable → backfill → add NOT NULL constraint nếu cần).

**Phụ thuộc bên ngoài:** PostgreSQL ≥ 14 (vì JSONB + GIN); MinIO/S3-compatible store.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test ≥ 80% coverage cho `ContentItemRepository`.
- [ ] Test TC-DF-T-06-002-* pass tự động trừ TC-07 (chạy thủ công có evidence).
- [ ] Migration chạy thành công trên staging + production; rollback script có sẵn.
- [ ] `docs/modules/content.md` cập nhật ERD.
- [ ] `docs/official_docs/modules/06-content-extraction-artifacts.md` không thay đổi nghiệp vụ nhưng link tới ticket.
- [ ] Telemetry: metric `content_item_insert_total{platform, content_type}`, `content_item_insert_size_raw_data_bytes` histogram.
- [ ] Code review ≥ 1 approve từ owner module Content và owner DB.
- [ ] Release notes nói rõ "Content item data model phiên bản 1 đã ship".
- [ ] Đã chạy test cross-tenant trên staging với 2 org thật để xác nhận isolation.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §5.3, §6 FR-06-05/06/07/12/13](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** Social Data Operator (§3.1), Automation Builder (§3.2).
- **Thuật ngữ:** [Content item](../../official_docs/00-glossary.md), [raw_data](../../official_docs/00-glossary.md), [parent_id / item_level](../../official_docs/00-glossary.md), [Artifact](../../official_docs/00-glossary.md).
- **Ma trận năng lực:** [03-capability-matrix.md §4.3 Execution artifact + Content collection](../../official_docs/03-capability-matrix.md).
- **Epic liên quan:** DF-E-02 (device_id), DF-E-04 (execution_id), DF-E-07 (account_id).
