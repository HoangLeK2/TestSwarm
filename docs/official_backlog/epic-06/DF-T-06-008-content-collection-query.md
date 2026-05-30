# DF-T-06-008 — Content collection CRUD + query/filter API

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-008 |
| **Title** | Content collection CRUD + query/filter API |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `layer:db`, `layer:frontend`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2` |
| **Truy vết — FR refs** | FR-06-10, FR-06-11 |
| **Truy vết — UC refs** | UC-06-07, UC-06-08, UC-06-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Social Data Operator vận hành hàng nghìn account và crawl theo dự án — không thể để mọi content item đổ chung 1 bể. Content collection là khái niệm gom theo project / khách hàng, có owner, có metadata mô tả, có lifecycle độc lập. Một content item thuộc một collection chính (nullable nếu là extract trực tiếp không gắn collection).

Ticket này dựng CRUD collection và query/filter API cho cả collection lẫn content item. API filter phải hỗ trợ kết hợp nhiều tiêu chí (platform, content_type, collection, campaign, execution, device, account, time range) và trả nhanh < 3 s cho top 1000 record (KPI module).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** tạo collection theo dự án, lọc content theo nhiều tiêu chí (platform, content type, thời gian, account), và trả về kết quả phân trang nhanh
> **Để** báo cáo cho khách hàng theo đúng phạm vi dự án không bị lẫn dữ liệu

Persona phụ: Automation Builder (khai báo collection_id trong scenario), Fleet Operator (kiểm tra collection đang phình to).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp endpoint:
  - `POST /api/content/collections` tạo collection (owner, name, description, project_tag, metadata).
  - `GET /api/content/collections` list theo organization với filter `owner_id, project_tag, q (name search)`.
  - `GET /api/content/collections/{id}` xem chi tiết kèm summary (count content, last extracted_at).
  - `PATCH /api/content/collections/{id}` update name/description/metadata.
  - `DELETE /api/content/collections/{id}` soft-delete (không cascade xóa content; có flag `cascade=true` để cascade soft-delete content trong đó).
- Hệ thống PHẢI cung cấp endpoint `GET /api/content/items` với filter: `collection_id, campaign_id, execution_id, device_id, account_id, platform, content_type[]`, `posted_at_from`, `posted_at_to`, `extracted_at_from`, `extracted_at_to`, `parent_id`, `item_level`, `q` (text search trong text_content), `cursor`, `limit` — trace FR-06-11.
- Hệ thống PHẢI hỗ trợ phân trang cursor-based (không offset-based) để scale tốt.
- Hệ thống PHẢI đạt p95 < 3 s cho query top 1000 record với filter kết hợp 3 tiêu chí — trace FR-06-11.
- Hệ thống PHẢI enforce organization filter mặc định mọi query (cross-tenant isolation).
- Hệ thống PHẢI cung cấp `GET /api/content/items/{id}/tree` trả cây hội thoại đầy đủ từ root tới max depth 10 — trace FR-06-07.
- Hệ thống PHẢI cung cấp `GET /api/content/collections/{id}/stats` trả {total_items, by_content_type, by_platform, date_range}.
- Hệ thống PHẢI hỗ trợ text search basic (LIKE / ILIKE; full-text search là Lộ trình).
- Hệ thống NÊN cho phép export pagination kết quả query ra JSON Lines stream (preview cho đường export refactor; sản phẩm cuối ở lộ trình).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo collection và lưu content vào**

```
Given user U thuộc org X
When U POST /api/content/collections {name:"FB Group - Đợt 5", project_tag:"clientA"}
Then trả 201 với collection_id
And U liệt kê collections, thấy collection mới ở đầu
```

**AC-2: Filter kết hợp**

```
Given org X có 50k content, trong đó 1500 thuộc collection C, platform=facebook, content_type=fb_post, extracted_at trong 7 ngày qua
When client GET /api/content/items?collection_id=C&platform=facebook&content_type=fb_post&extracted_at_from=NOW-7D&limit=100
Then trả 100 entry đầu + next_cursor
And p95 latency < 3 s
And tổng đếm 1500 trong header X-Total-Count
```

**AC-3: Cross-tenant isolation**

```
Given collection C thuộc org X
When user U thuộc org Y GET /api/content/collections/{C.id}
Then trả 404
```

**AC-4: Cây hội thoại**

```
Given post P có 5 comment, 3 comment có reply (tổng 12 content)
When GET /api/content/items/{P.id}/tree
Then trả cây với P là root, 5 comment level 2, 3 reply level 3
And tree sắp xếp theo posted_at asc
```

**AC-5: Soft-delete collection không cascade**

```
Given collection C chứa 100 content
When DELETE /api/content/collections/{C.id} (không cascade flag)
Then collection bị mark deleted_at
And 100 content_item vẫn truy vấn được; collection_id của chúng vẫn = C.id
And UI hiển thị collection ở section "Deleted (recoverable 30 ngày)"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm export định dạng cuối (CSV / JSON archive) — đang refactor (xem module §8); preview ở DF-T-06-012 nếu phù hợp.
- KHÔNG bao gồm full-text search (PostgreSQL tsvector hoặc Elastic) — Lộ trình.
- KHÔNG bao gồm share collection cross-organization — không có trong scope module.
- KHÔNG bao gồm collection permission granular per user — chỉ owner + organization scope.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Repository `ContentCollectionRepository` với CRUD + soft-delete.
- [ ] Repository `ContentItemQueryService` với filter builder (chấp nhận dict filter, trả query SQLAlchemy/SQL).
- [ ] Cursor-based pagination (id + extracted_at composite).
- [ ] Tree builder (recursive CTE) cho `/tree`.
- [ ] Stats aggregator cho `/stats`.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI spec cho 7 endpoint.
- [ ] Response schema chuẩn (envelope `{data, meta:{cursor, total}}`).
- [ ] Mã lỗi `COLLECTION_NOT_FOUND`, `INVALID_CURSOR`, `FILTER_INVALID`.

**Database / Migration** (`layer:db`)

- [ ] Index xác nhận từ DF-T-06-002 đủ.
- [ ] Add index `(organization_id, collection_id, extracted_at DESC)` nếu chưa có.
- [ ] Index `(parent_id)` cho tree.

**Frontend** (`layer:frontend`)

- [ ] List/CRUD collection UI (placeholder; chi tiết ở DF-E-11).
- [ ] Filter panel + pagination cho content listing (placeholder).

**Documentation** (`layer:docs`)

- [ ] OpenAPI publish trong `docs/api/content.md`.
- [ ] Hướng dẫn "Cách tạo collection cho 1 dự án".

**Test** (`layer:test`)

- [ ] Integration test CRUD collection.
- [ ] Integration test filter (positive, negative, edge).
- [ ] Load test 100k record, query với 3 filter, đo p95.
- [ ] Test cross-tenant isolation.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-008-01 | Positive | Org X có 1500 content thuộc collection C | GET /items với filter collection_id=C | Trả 100 entry đầu + next_cursor; X-Total-Count = 1500 |
| TC-DF-T-06-008-02 | Positive | Post P có 12 descendant | GET /items/{P.id}/tree | Tree đúng cấu trúc; depth ≤ 3 |
| TC-DF-T-06-008-03 | Negative | User U thuộc org Y; collection C thuộc org X | GET /collections/{C.id} | 404; audit log cross-tenant |
| TC-DF-T-06-008-04 | Negative | Filter `content_type=invalid_type` | GET /items | 400 `FILTER_INVALID`; gợi ý content_type hợp lệ |
| TC-DF-T-06-008-05 | Edge | 100k content trong 1 collection; query 3 filter | Load test | p95 < 3 s; không OOM |
| TC-DF-T-06-008-06 | Edge | Cursor pagination từ trang 1 đến hết 1500 record | Loop GET với next_cursor | Mỗi page đúng 100; không trùng entry; không miss entry |
| TC-DF-T-06-008-07 | Edge | DELETE collection có 100 content, cascade=false | DELETE + GET items | Collection soft-deleted; content vẫn query được; UI hiển thị warning |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-001 (registry để validate content_type filter), DF-T-06-002 (data model).

**Chặn:** DF-T-06-009 (cần collection để gắn content), DF-T-06-010 (dedup theo collection scope).

**Phụ thuộc giữa Epic:** DF-E-11 (Frontend) sẽ build UI tiêu thụ API này.

**Rủi ro:**

- **Query với nhiều filter kết hợp chậm trên DB lớn:** giảm thiểu: profile EXPLAIN ANALYZE, thêm composite index khi cần.
- **Cursor không stable nếu sort key không unique:** giảm thiểu: cursor = (extracted_at, id) tuple đảm bảo total order.

**Phụ thuộc bên ngoài:** PostgreSQL recursive CTE cho tree.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] 7 endpoint qua integration test pass.
- [ ] Load test 100k record p95 < 3 s đạt.
- [ ] OpenAPI publish.
- [ ] Telemetry: `query_latency_ms{endpoint}`, `query_filter_combo_total{combo}` (tracking filter pattern).
- [ ] Code review ≥ 1 approve owner module + 1 approve owner DB.
- [ ] Frontend DF-E-11 confirm contract phù hợp.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §6 FR-06-10, FR-06-11](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** Social Data Operator (§3.1).
- **Thuật ngữ:** [Content collection](../../official_docs/00-glossary.md), [Content item](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-11.
