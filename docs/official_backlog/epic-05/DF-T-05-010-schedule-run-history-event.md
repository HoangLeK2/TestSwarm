# DF-T-05-010 — Schedule run history + link execution + domain event

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-010 |
| **Title** | Schedule run history + link execution + domain event |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Lập lịch |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | `Done` |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:contract`, `type:feature`, `persona:operator` |
| **Truy vết — FR refs** | FR-05-07, FR-05-11, FR-05-12 |
| **Truy vết — UC refs** | UC-05-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Schedule không có lịch sử là black box. Ticket này là source of truth cho audit schedule run.

Đọc nhanh cho dev: triển khai run history, link execution và domain event cho schedule. Điểm cần chốt khi code là history record phải có run_id idempotent theo schedule_id + scheduled_at; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** mỗi tick tạo schedule_run có link execution
> **Để** truy vết được lịch sử và gửi notification khi run terminal

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI ghi lịch sử từng lần schedule được tick/run-now.
- Hệ thống PHẢI link execution_id khi dispatch tạo execution thành công.
- Hệ thống PHẢI emit domain event cho run started/finished/failed.
- Hệ thống PHẢI chống duplicate history khi scheduler retry cùng tick.
- Hệ thống PHẢI cho query history theo schedule/status/time range.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: run history, link execution và domain event cho schedule - luồng thành công**

```gherkin
Given schedule được tick hoặc run-now và campaign execution được tạo hoặc fail trước dispatch
When scheduler xử lý một lần run của schedule
Then run history ghi scheduled_at/started_at/status và link execution_id nếu có
And domain event `schedule.run_started/run_finished/run_failed` được phát đúng organization
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-05-010
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given execution_id không thuộc organization, duplicate tick hoặc schedule bị disabled trước khi ghi history
When hệ thống xử lý request/event của DF-T-05-010
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Reconnect, debounce và backpressure an toàn**

```gherkin
Given consumer mất kết nối hoặc xử lý chậm trong lúc event phát liên tục
When consumer reconnect hoặc backlog vượt ngưỡng
Then hệ thống áp dụng snapshot/replay/debounce theo contract của DF-T-05-010
And metric/log backpressure đủ để điều tra sự cố
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given scheduler retry cùng tick, execution fail trước khi có id và history list phân trang dài
When chạy test tích hợp hoặc staging cho DF-T-05-010
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI chi tiết — DF-E-11.
- KHÔNG bao gồm thay đổi campaign execution engine — DF-E-04.
- KHÔNG bao gồm BI dashboard nâng cao ngoài KPI module — DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai history writer idempotent và event publisher sau transaction.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-05-010: history record phải có run_id idempotent theo schedule_id + scheduled_at.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] bảng schedule_run_history có unique key chống duplicate tick.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới run history, link execution và domain event cho schedule.
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
| TC-DF-T-05-010-01 | Positive | schedule được tick hoặc run-now và campaign execution được tạo hoặc fail trước dispatch | scheduler xử lý một lần run của schedule | run history ghi scheduled_at/started_at/status và link execution_id nếu có |
| TC-DF-T-05-010-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | domain event `schedule.run_started/run_finished/run_failed` được phát đúng organization |
| TC-DF-T-05-010-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-05-010 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-05-010-04 | Negative | execution_id không thuộc organization, duplicate tick hoặc schedule bị disabled trước khi ghi history | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-05-010-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-05-010-06 | Edge | scheduler retry cùng tick, execution fail trước khi có id và history list phân trang dài | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-05-010-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-05-001, DF-T-05-002.

**Chặn:** DF-T-09-001.

**Phụ thuộc giữa Epic:** DF-E-04 cung cấp execution; DF-E-09 tiêu thụ domain event; DF-E-11 hiển thị UI.

**Rủi ro:**

- **R1 — Duplicate tick tạo nhiều history/run; giảm thiểu bằng idempotency key schedule_id + scheduled_at.**
- **R2 — Event phát trước transaction commit làm consumer thấy record chưa tồn tại; giảm thiểu bằng outbox/after-commit publish.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-05-010` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — FR-05-07, FR-05-11, FR-05-12.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
