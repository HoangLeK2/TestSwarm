# DF-T-09-014 — Ad-hoc query API for analytics

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-014 |
| **Title** | Ad-hoc query API for analytics |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:contract`, `type:feature`, `persona:operator` |
| **Truy vết — FR refs** | FR-09-11 |
| **Truy vết — UC refs** | UC-09-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Ad-hoc API phải có allowlist field, limit và RBAC để không biến thành SQL console nguy hiểm.

Đọc nhanh cho dev: triển khai ad-hoc query API cho analytics. Điểm cần chốt khi code là request schema phải whitelist metric/dimension/operator và giới hạn time_range/limit; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** query analytics activity với bộ lọc linh hoạt có guardrail
> **Để** supervisor trả lời câu hỏi vận hành không cần truy cập DB trực tiếp

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp ad-hoc query API theo metric/dimension whitelist.
- Hệ thống PHẢI giới hạn time range, row limit và operator được phép.
- Hệ thống PHẢI luôn áp organization scope và không nhận raw SQL từ client.
- Hệ thống PHẢI audit query quan trọng và emit latency metric.
- Hệ thống PHẢI trả lỗi rõ khi metric/dimension không hỗ trợ.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: ad-hoc query API cho analytics - luồng thành công**

```gherkin
Given analytics data đã ingest và có whitelist dimensions/metrics
When Supervisor gọi ad-hoc query với metric, dimension, filter và time range
Then API trả kết quả aggregate trong organization theo whitelist, không cho raw SQL hoặc field ngoài contract
And query được audit/metric với time range, dimensions và row count
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-09-014
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given metric/dimension không hỗ trợ, time range vượt giới hạn hoặc filter khác organization
When hệ thống xử lý request/event của DF-T-09-014
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Read-only và pagination ổn định**

```gherkin
Given dữ liệu liên quan thay đổi trong lúc client đang đọc hoặc phân trang
When client gọi lại cùng filter/sort của DF-T-09-014
Then hệ thống không tạo side-effect trong database
And pagination/sort vẫn ổn định, không mất hoặc nhân đôi bản ghi ngoài giới hạn đã document
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given kết quả rỗng, query sát limit row/time và nhiều query đồng thời
When chạy test tích hợp hoặc staging cho DF-T-09-014
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI notification panel/dashboard — DF-E-11.
- KHÔNG bao gồm Prometheus/distributed tracing — DF-E-01.
- KHÔNG bao gồm BI warehouse chuyên sâu — ngoài phạm vi DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai query planner an toàn map sang aggregate query, enforce timeout/limit.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-09-014: request schema phải whitelist metric/dimension/operator và giới hạn time_range/limit.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] index/materialized view cho metric chính nếu query trực tiếp quá chậm.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới ad-hoc query API cho analytics.
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
| TC-DF-T-09-014-01 | Positive | analytics data đã ingest và có whitelist dimensions/metrics | Supervisor gọi ad-hoc query với metric, dimension, filter và time range | API trả kết quả aggregate trong organization theo whitelist, không cho raw SQL hoặc field ngoài contract |
| TC-DF-T-09-014-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | query được audit/metric với time range, dimensions và row count |
| TC-DF-T-09-014-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-09-014 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-09-014-04 | Negative | metric/dimension không hỗ trợ, time range vượt giới hạn hoặc filter khác organization | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-09-014-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-09-014-06 | Edge | kết quả rỗng, query sát limit row/time và nhiều query đồng thời | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-09-014-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-001.

**Chặn:** DF-T-11-015.

**Phụ thuộc giữa Epic:** DF-E-11 tiêu thụ API; mọi domain Epic phát event qua DF-E-09.

**Rủi ro:**

- **R1 — Ad-hoc API thành raw SQL injection surface; giảm thiểu bằng whitelist DSL, không nhận SQL.**
- **R2 — Query nặng ảnh hưởng production DB; giảm thiểu bằng limit/timeout/materialized summary.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-09-014` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — FR-09-11.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
