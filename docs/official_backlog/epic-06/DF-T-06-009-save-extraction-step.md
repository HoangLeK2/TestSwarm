# DF-T-06-009 — `save_extraction` scenario step + endpoint extract trực tiếp

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-009 |
| **Title** | `save_extraction` scenario step + endpoint extract trực tiếp |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:automation-builder`, `coverage:L2` |
| **Truy vết — FR refs** | FR-06-08, FR-06-09 |
| **Truy vết — UC refs** | UC-06-04, UC-06-09, UC-06-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đây là ticket "khóa van" của Epic — đường nghiệp vụ chính để content vào DB. Đặc tả module định nghĩa 2 đường gọi extraction:

1. **Scenario step `save_extraction`** — đường chuẩn cho workflow tự động. Step nhận tham số `engine` (hierarchy/ocr/ai), `strategy_or_prompt`, `content_type`, `collection_id`, `dedup_key_field`, error policy.
2. **Endpoint `/api/devices/{serial}/extract/{hierarchy|ocr|ai}`** — đường nhanh ngoài scenario, dùng khi Automation Builder đang reserve device và muốn thử strategy nhanh, hoặc tích hợp ngoài.

Cả 2 đường dùng **cùng** handler, **cùng** engine, **cùng** normalizer, **cùng** schema content_item. Đặc tả module ghi rõ: "không tồn tại bản ghi 'extract ngoài scenario' có schema khác với 'extract trong scenario'."

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** khai báo step `save_extraction` trong scenario hoặc gọi endpoint extract trực tiếp khi đang reserve device, và cả 2 đường đều lưu cùng schema content
> **Để** không phải quản lý 2 codepath khác nhau cho cùng 1 nghiệp vụ

Persona phụ: Social Data Operator (tiêu thụ kết quả).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp step type `save_extraction` chạy trong scenario executor với schema:
  ```
  { type: "save_extraction",
    engine: "hierarchy" | "ocr" | "ai",
    strategy: <strategy_name> | prompt: <ai_prompt>,
    content_type: "fb_post" | "fb_comment" | ...,
    collection_id: <uuid>,
    dedup_key_field: <field_name> | null,
    error_policy: { on_error: "fail" | "skip" | "branch", retry: {...} } }
  ```
- Hệ thống PHẢI cung cấp 3 endpoint:
  - `POST /api/devices/{serial}/extract/hierarchy` body `{strategy, config, persist:bool, content_type?, collection_id?}`.
  - `POST /api/devices/{serial}/extract/ocr` body `{region?, lang?, persist:bool, content_type?, collection_id?}`.
  - `POST /api/devices/{serial}/extract/ai` body `{prompt, expected_schema, provider?, model?, persist:bool, content_type?, collection_id?}`.
- Hệ thống PHẢI yêu cầu thiết bị `serial` đang reserve cho session gọi (trả 409 nếu không) — trace FR-06-09.
- Hệ thống PHẢI có cờ `persist`: true → lưu content_item; false → chỉ trả về result.
- Hệ thống PHẢI idempotent theo `dedup_key_field`: re-run trên cùng input + dedup key → không tạo bản ghi trùng — trace FR-06-08.
- Hệ thống PHẢI điền đầy đủ trace ids (campaign, scenario, execution, device, account) khi gọi qua scenario step.
- Hệ thống PHẢI điền `is_direct_extract=true` và trace ids null khi gọi qua endpoint trực tiếp không có context campaign.
- Hệ thống PHẢI gọi normalizer trước khi lưu (DF-T-06-007).
- Hệ thống PHẢI áp `content_type` validation (DF-T-06-001).
- Hệ thống PHẢI áp error_policy của scenario; thất bại được tiêu thụ bởi error handling (DF-T-06-014).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: save_extraction trong scenario chạy thành công**

```
Given scenario S có step save_extraction { engine:hierarchy, strategy:fb_posts, content_type:fb_post, collection_id:C, dedup_key_field:external_id }
And dispatch trên device D với account A
When executor chạy step
Then engine → normalize → save thành content_item type fb_post
And content_item có collection_id=C, campaign_id, scenario_id=S, execution_id, device_id=D, account_id=A
And artifact (hierarchy snapshot) đính kèm execution
```

**AC-2: Endpoint trực tiếp với persist=false**

```
Given user U có session reserve device D
When U POST /api/devices/{D.serial}/extract/hierarchy {strategy:fb_posts, persist:false}
Then trả 200 với result data + raw_data
And KHÔNG có content_item nào được tạo
And artifact pre/post vẫn được lưu nếu user khai báo capture (mặc định không capture)
```

**AC-3: Endpoint trực tiếp với persist=true ngoài campaign**

```
Given user U reserve device D
When U POST /api/devices/{D.serial}/extract/hierarchy {strategy:fb_posts, persist:true, content_type:fb_post, collection_id:C}
Then trả 200 + content_item_id
And content_item có collection_id=C, device_id=D, is_direct_extract=true
And campaign_id, scenario_id, execution_id null
```

**AC-4: Idempotent với dedup_key_field**

```
Given collection C; dedup_key_field=external_id
And run scenario lần 1, lưu được 50 fb_post với external_id distinct
When chạy scenario lần 2 trên cùng data (cùng external_id)
Then không có content_item mới được tạo (50 + 0)
And metric `save_extraction_dedup_hit_total` tăng 50
And response step có field `dedup_skipped=50`
```

**AC-5: Device chưa reserve**

```
Given device D chưa reserve cho user U
When U POST /api/devices/{D.serial}/extract/hierarchy
Then 409 `DEVICE_NOT_RESERVED`
And không có engine call nào diễn ra
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm server-side dedup global cho collection (chỉ dedup theo dedup_key_field trong cùng save_extraction call) — đó là DF-T-06-010.
- KHÔNG bao gồm step `extract` không lưu (dry-run trong scenario) — chỉ qua endpoint trực tiếp persist=false.
- KHÔNG bao gồm bulk extraction multiple URL trong 1 step — sẽ làm sau nếu có demand.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Step handler `SaveExtractionStepHandler` đăng ký với scenario executor (DF-E-04).
- [ ] 3 endpoint REST `/api/devices/{serial}/extract/*` cùng dùng common handler.
- [ ] Common handler: validate reserve → gọi engine (qua DF-T-06-004/005/006) → normalize (DF-T-06-007) → dedup local theo dedup_key_field → save content_item.
- [ ] Trace ids inject từ execution context (DF-E-04).
- [ ] Error policy interpreter.

**Contract / API** (`layer:contract`)

- [ ] Step schema JSON.
- [ ] OpenAPI cho 3 endpoint.
- [ ] Mã lỗi `DEVICE_NOT_RESERVED`, `EXTRACTION_FAILED`, `DEDUP_KEY_MISSING_IN_RESULT`.

**Documentation** (`layer:docs`)

- [ ] "save_extraction step reference" trong `docs/modules/content.md`.
- [ ] Sequence diagram 2 đường gọi.
- [ ] Ví dụ scenario JSON với save_extraction.

**Test** (`layer:test`)

- [ ] Unit test handler.
- [ ] Integration test scenario chạy save_extraction trên emulator.
- [ ] Test idempotent (chạy lại 3 lần).
- [ ] Test endpoint persist=false vs persist=true.
- [ ] Test cross-tenant reserve.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-009-01 | Positive | Scenario với save_extraction; device pair với account; collection C tồn tại | Dispatch scenario | content_item lưu với đầy đủ trace ids; artifact đính kèm |
| TC-DF-T-06-009-02 | Positive | User reserve device D; endpoint trực tiếp | POST /extract/hierarchy persist=false | Trả result + raw_data; không có content_item |
| TC-DF-T-06-009-03 | Negative | Device D chưa reserve | POST /extract/hierarchy | 409 DEVICE_NOT_RESERVED |
| TC-DF-T-06-009-04 | Negative | content_type="post" (generic) trong save_extraction | Chạy step | Step fail với CONTENT_TYPE_GENERIC_REJECTED; scenario error policy quyết định tiếp |
| TC-DF-T-06-009-05 | Edge | Chạy save_extraction 3 lần trên cùng data với dedup_key_field=external_id | 3 lần dispatch | Lần 1: 50 insert; lần 2,3: 0 insert; metric dedup_hit = 100 |
| TC-DF-T-06-009-06 | Edge | dedup_key_field khai báo nhưng result không có field đó | Chạy step | Lỗi `DEDUP_KEY_MISSING_IN_RESULT`; không silent dedup theo random field |
| TC-DF-T-06-009-07 | Edge | Engine fail (provider AI timeout) + retry policy 2 lần | Step | Thử lại 2 lần; nếu cả 2 fail → on_error policy quyết định (skip / fail) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-001, DF-T-06-002, DF-T-06-003, DF-T-06-004, DF-T-06-005, DF-T-06-006, DF-T-06-007, DF-T-06-008.

**Chặn:** DF-E-04 (scenario crawl không chạy được nếu chưa có step này), DF-T-06-010, DF-T-06-014.

**Phụ thuộc giữa Epic:** DF-E-04 (scenario executor) phải đăng ký handler step. DF-E-02 (device reserve check) phải expose API check ownership.

**Rủi ro:**

- **Step idempotent race condition khi 2 step parallel cùng dedup key:** giảm thiểu: unique constraint optional (collection_id, dedup_key_value); INSERT ... ON CONFLICT DO NOTHING.
- **Endpoint trực tiếp bị lạm dụng (skip scenario):** giảm thiểu: rate limit per session 60 req/phút; audit log mọi call.

**Phụ thuộc bên ngoài:** DF-E-04 (scenario executor), DF-E-02 (device reserve).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] save_extraction step chạy thành công trên scenario thực với 3 engine.
- [ ] 3 endpoint qua integration test pass.
- [ ] Idempotent test pass 3 vòng.
- [ ] `docs/modules/content.md` có sequence diagram.
- [ ] Telemetry: `save_extraction_total{engine, content_type, result}`, `save_extraction_dedup_hit_total`, `direct_extract_total{engine}`.
- [ ] Code review ≥ 1 approve owner module + 1 approve owner Epic-04.
- [ ] Changelog + release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §5.4, §6 FR-06-08, FR-06-09](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** Automation Builder (§3.2).
- **Thuật ngữ:** [save_extraction](../../official_docs/00-glossary.md), [Extraction strategy](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-04, DF-E-02.
