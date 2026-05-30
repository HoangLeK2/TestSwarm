# DF-T-09-013 — Audit trail report

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-013 |
| **Title** | Audit trail report |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:contract`, `type:feature`, `persona:operator` |
| **Truy vết — FR refs** | FR-09-10, FR-09-11 |
| **Truy vết — UC refs** | UC-09-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Activity log chỉ hữu ích khi có cách trích xuất đáng tin cậy. Ticket này chuẩn hóa report CSV theo filter và quyền truy cập.

Đọc nhanh cho dev: triển khai audit trail report. Điểm cần chốt khi code là report schema phải có actor, action, resource_type/id, timestamp, source_module và request_id; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** export activity log theo filter
> **Để** admin có evidence phục vụ audit hoặc điều tra sự cố

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cho admin query audit trail theo actor/action/resource/time range.
- Hệ thống PHẢI hỗ trợ export report có phân trang hoặc job async khi dữ liệu lớn.
- Hệ thống PHẢI redaction field nhạy cảm trong report.
- Hệ thống PHẢI audit chính hành động export/report.
- Hệ thống PHẢI giữ organization scope và admin-only access.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: audit trail report - luồng thành công**

```gherkin
Given organization có audit/activity records từ nhiều module
When Admin tổ chức query hoặc export audit trail theo filter
Then report trả bản ghi đúng organization theo actor/action/resource/time range, có pagination/export và redaction dữ liệu nhạy cảm
And export/report generation được audit với filter và requester
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-09-013
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given caller không phải admin, time range quá lớn hoặc filter trỏ resource khác organization
When hệ thống xử lý request/event của DF-T-09-013
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Read-only và pagination ổn định**

```gherkin
Given dữ liệu liên quan thay đổi trong lúc client đang đọc hoặc phân trang
When client gọi lại cùng filter/sort của DF-T-09-013
Then hệ thống không tạo side-effect trong database
And pagination/sort vẫn ổn định, không mất hoặc nhân đôi bản ghi ngoài giới hạn đã document
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given không có record, dataset lớn, export timeout và record từ nhiều module cùng resource_id
When chạy test tích hợp hoặc staging cho DF-T-09-013
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI notification panel/dashboard — DF-E-11.
- KHÔNG bao gồm Prometheus/distributed tracing — DF-E-01.
- KHÔNG bao gồm BI warehouse chuyên sâu — ngoài phạm vi DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai query/export service admin-only có filter whitelist và redaction.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-09-013: report schema phải có actor, action, resource_type/id, timestamp, source_module và request_id.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] index audit theo organization_id, created_at, actor_id, action, resource_type.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới audit trail report.
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
| TC-DF-T-09-013-01 | Positive | organization có audit/activity records từ nhiều module | Admin tổ chức query hoặc export audit trail theo filter | report trả bản ghi đúng organization theo actor/action/resource/time range, có pagination/export và redaction dữ liệu nhạy cảm |
| TC-DF-T-09-013-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | export/report generation được audit với filter và requester |
| TC-DF-T-09-013-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-09-013 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-09-013-04 | Negative | caller không phải admin, time range quá lớn hoặc filter trỏ resource khác organization | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-09-013-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-09-013-06 | Edge | không có record, dataset lớn, export timeout và record từ nhiều module cùng resource_id | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-09-013-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-001.

**Chặn:** DF-T-11-015.

**Phụ thuộc giữa Epic:** DF-E-11 tiêu thụ API; mọi domain Epic phát event qua DF-E-09.

**Rủi ro:**

- **R1 — Report lộ dữ liệu tenant hoặc secret; giảm thiểu bằng org scope và redaction DTO.**
- **R2 — Export lớn làm timeout API; giảm thiểu bằng async job hoặc pagination.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-09-013` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — FR-09-10, FR-09-11.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
