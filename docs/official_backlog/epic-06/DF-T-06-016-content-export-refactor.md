# DF-T-06-016 — Content export refactor sau migration drop export cũ

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-016 |
| **Title** | Content export refactor sau migration drop export cũ |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-06-10, FR-06-11, FR-06-12, Lộ trình: export content refactor |
| **Truy vết — UC refs** | UC-06-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Lộ trình ngắn hạn yêu cầu refactor export content sau migration `031_drop_content_exports` xóa export cũ. Hiện UI content browser có nhu cầu bulk export, nhưng scope backend chưa có ticket riêng. Nếu để frontend tự xử lý export, dữ liệu lớn dễ làm OOM client, thiếu audit, thiếu retention và dễ lệch organization scope.

Đọc nhanh cho dev: ticket này biến một requirement trong lộ trình thành phạm vi triển khai có thể nghiệm thu độc lập. Không gom thêm UI polish, draft platform hoặc refactor ngoài phạm vi; các phần backend, frontend và test phải bám trực tiếp vào `Tiêu chí chấp nhận` và `Test case nghiệp vụ` của ticket này.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator  
> **Tôi muốn** export content collection theo filter bằng API server-side ổn định  
> **Để** lấy dữ liệu sau crawl ra CSV/JSON mà không phụ thuộc export cũ đã bị drop

Persona phụ: Không.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp API tạo export job theo collection/filter hiện tại — trace FR-06-10/11.
- Hệ thống PHẢI hỗ trợ format CSV và JSONL với schema version rõ ràng.
- Hệ thống PHẢI stream hoặc async job server-side cho export lớn, không tải toàn bộ dataset vào memory.
- Hệ thống PHẢI lưu artifact export vào MinIO/S3 với TTL/retention cấu hình — trace FR-06-12.
- Hệ thống PHẢI ghi audit user, filter, số dòng, format, thời điểm tạo/tải export.
- Hệ thống PHẢI từ chối export cross-tenant và export dữ liệu đã hết retention.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo export job từ collection hợp lệ**

```gherkin
Given user có quyền trên collection và filter hợp lệ
When user gọi create export job CSV
Then job chuyển queued/running rồi completed
And artifact export có signed URL và row count đúng
```

**AC-2: Export theo filter đang áp dụng**

```gherkin
Given collection có nhiều platform/content_type
When user export chỉ `platform=tiktok` và date range cụ thể
Then file chỉ chứa item đúng filter
And metadata ghi filter đã dùng
```

**AC-3: Từ chối cross-tenant**

```gherkin
Given user org A biết id collection org B
When user gọi export collection org B
Then API trả 403/404
And không tạo export job hoặc audit artifact
```

**AC-4: Dataset lớn không làm OOM**

```gherkin
Given collection có 100k content item
When user tạo export JSONL
Then job xử lý streaming/chunked
And memory nằm trong ngưỡng và file đầy đủ
```

**AC-5: Retry tải artifact hết hạn**

```gherkin
Given export artifact đã hết TTL
When user mở signed URL cũ
Then server trả 403 rõ ràng
And user có thể tạo export mới nếu còn quyền
```

**AC-6: Idempotency khi retry create**

```gherkin
Given client timeout sau create export
When client retry cùng idempotency key
Then không tạo job trùng
And response trả job hiện có
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI content browser — DF-T-11-009 chỉ consume API.
- KHÔNG bao gồm warehouse/BI pipeline chuyên sâu ngoài CSV/JSONL.
- KHÔNG bao gồm retention policy tổng cho mọi artifact — DF-T-06-011.
- KHÔNG bao gồm export activity log/audit report — DF-E-09.

## 7. Kế hoạch triển khai

**Implementation**

- [ ] Thiết kế `content_exports` job model mới nếu cần.
- [ ] Implement endpoint create/get/download export job.
- [ ] Thêm worker xử lý export chunked/streaming.
- [ ] Thêm schema version cho CSV/JSONL.
- [ ] Tích hợp artifact store và signed URL.
- [ ] Emit audit event `content.export.created/downloaded/failed`.
- [ ] Cập nhật DF-T-11-009 để bỏ backend scope khỏi UI ticket.

**Test**

- [ ] Unit test cho rule nghiệp vụ chính.
- [ ] Integration test cho API/event/schema liên quan.
- [ ] E2E hoặc manual evidence cho luồng người dùng nếu có UI.
- [ ] Map từng test case bên dưới vào automated/manual evidence.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-016-01 | Positive | Collection 500 item, user có quyền | Tạo CSV export | Job completed, file có đúng 500 row |
| TC-DF-T-06-016-02 | Positive | Filter platform/content_type/date hợp lệ | Tạo JSONL export | File chỉ có item đúng filter, metadata ghi schema version |
| TC-DF-T-06-016-03 | Negative | Collection thuộc org khác | Gọi export | 403/404, không tạo job |
| TC-DF-T-06-016-04 | Negative | Filter invalid hoặc format không hỗ trợ | Gọi create export | 400 với mã lỗi rõ, không ghi job |
| TC-DF-T-06-016-05 | Edge | 100k item | Export chunked | Không OOM, job progress cập nhật |
| TC-DF-T-06-016-06 | Edge | Retry cùng idempotency key | Gọi create export 2 lần | Chỉ có một job |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-002, DF-T-06-008, DF-T-06-011.

**Chặn:** DF-T-11-009.

**Phụ thuộc giữa Epic:** DF-E-11 tiêu thụ export API; DF-E-09 có thể nhận audit event export.

**Rủi ro:**

- **R1 — Export lớn gây tải DB:** Giảm thiểu bằng pagination keyset/chunked streaming và giới hạn max row per job.
- **R2 — Leak dữ liệu tenant:** Mọi query phải enforce org scope và có integration test cross-tenant.
- **R3 — Schema CSV thay đổi phá consumer:** Gắn schema version và release note cho breaking change.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code/tài liệu merged và pass CI.
- [ ] Test case đã được map sang automated test hoặc manual evidence.
- [ ] API contract, event schema hoặc generated client cập nhật nếu thay đổi.
- [ ] Documentation trong `docs/official_docs` và ma trận năng lực cập nhật khi trạng thái coverage thay đổi.
- [ ] Telemetry/audit event cho path quan trọng đã có.
- [ ] Release notes/changelog ghi rõ impact và known limitation.

## 11. Truy vết & tài liệu tham chiếu

- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — ngắn hạn: export content refactor.
- **Đặc tả module:** [06-content-extraction-artifacts.md](../../official_docs/modules/06-content-extraction-artifacts.md) — FR-06-10, FR-06-11, FR-06-12.
- **UI liên quan:** DF-T-11-009.
