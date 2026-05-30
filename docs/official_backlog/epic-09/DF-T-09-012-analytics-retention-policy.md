# DF-T-09-012 — Analytics retention policy

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-012 |
| **Title** | Analytics retention policy |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:contract`, `type:feature`, `persona:operator` |
| **Truy vết — FR refs** | FR-09-10 |
| **Truy vết — UC refs** | UC-09-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module cảnh báo activity_log grow nhanh. Ticket này đưa retention thành product capability có config và audit.

Đọc nhanh cho dev: triển khai retention policy cho analytics/notification data. Điểm cần chốt khi code là retention policy phải phân biệt data_type, retention_days, action purge/archive/aggregate và legal_hold; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** thiết lập retention activity_log/notification theo organization
> **Để** database không tăng vô hạn nhưng audit vẫn kiểm soát được

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI khai báo retention theo data_type và organization nếu cần.
- Hệ thống PHẢI purge/archive/aggregate dữ liệu hết hạn theo batch an toàn.
- Hệ thống PHẢI không xóa audit-sensitive data khi policy hoặc legal hold cấm.
- Hệ thống PHẢI có dry-run hoặc summary trước/sau job.
- Hệ thống PHẢI emit metric và audit cho retention job.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: retention policy cho analytics/notification data - luồng thành công**

```gherkin
Given system có notification, activity log và analytics event cũ vượt retention window
When retention job chạy theo lịch hoặc admin cập nhật policy
Then dữ liệu analytics hết hạn được purge/aggregate theo policy mà vẫn giữ audit bắt buộc theo yêu cầu
And retention job ghi summary deleted/archived/skipped và metric duration/error
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-09-012
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given policy retention ngắn hơn minimum, thiếu approval cho audit-sensitive data hoặc job chạy khác organization
When hệ thống xử lý request/event của DF-T-09-012
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/concurrency không tạo quyết định trùng**

```gherkin
Given scheduler retry cùng tick hoặc nhiều request chạm cùng resource gần như đồng thời
When retention job chạy theo lịch hoặc admin cập nhật policy
Then hệ thống chỉ ghi một quyết định cuối cùng hợp lệ cho cùng idempotency key/resource
And mọi quyết định defer/skip/fail đều có lý do truy vết được
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given dataset lớn, job retry sau fail và policy thay đổi giữa job
When chạy test tích hợp hoặc staging cho DF-T-09-012
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI notification panel/dashboard — DF-E-11.
- KHÔNG bao gồm Prometheus/distributed tracing — DF-E-01.
- KHÔNG bao gồm BI warehouse chuyên sâu — ngoài phạm vi DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai retention worker có dry-run, batch delete/archive và safety guard.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-09-012: retention policy phải phân biệt data_type, retention_days, action purge/archive/aggregate và legal_hold.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] index theo organization_id, data_type, created_at; audit job history.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới retention policy cho analytics/notification data.
- [ ] Cập nhật `docs/official_docs` nếu contract hoặc nghiệp vụ nhìn thấy từ phía user thay đổi.
- [ ] Cập nhật changelog/release notes khi ticket ship.

**Test** (`layer:test`)

- [ ] Viết unit test cho validation/state rule chính.
- [ ] Viết integration test map trực tiếp AC-1 đến AC-5.
- [ ] Bổ sung negative test cho permission, organization scope và mã lỗi nghiệp vụ.
- [ ] Bổ sung boundary/resilience test theo TC-06/TC-07.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-012-01 | Positive | system có notification, activity log và analytics event cũ vượt retention window | retention job chạy theo lịch hoặc admin cập nhật policy | dữ liệu analytics hết hạn được purge/aggregate theo policy mà vẫn giữ audit bắt buộc theo yêu cầu |
| TC-DF-T-09-012-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | retention job ghi summary deleted/archived/skipped và metric duration/error |
| TC-DF-T-09-012-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-09-012 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-09-012-04 | Negative | policy retention ngắn hơn minimum, thiếu approval cho audit-sensitive data hoặc job chạy khác organization | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-09-012-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-09-012-06 | Edge | dataset lớn, job retry sau fail và policy thay đổi giữa job | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-09-012-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-001.

**Chặn:** DF-T-11-015.

**Phụ thuộc giữa Epic:** DF-E-11 tiêu thụ API; mọi domain Epic phát event qua DF-E-09.

**Rủi ro:**

- **R1 — Retention xóa nhầm audit evidence; giảm thiểu bằng legal_hold/minimum retention guard.**
- **R2 — Batch delete lớn gây lock DB; giảm thiểu bằng chunking và time budget.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-09-012` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — FR-09-10.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
