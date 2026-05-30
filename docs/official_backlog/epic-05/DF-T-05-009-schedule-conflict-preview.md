# DF-T-05-009 — Schedule conflict detection & preview API

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-009 |
| **Title** | Schedule conflict detection & preview API |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Lập lịch |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:contract`, `type:feature`, `persona:operator` |
| **Truy vết — FR refs** | FR-05-02, FR-05-07 |
| **Truy vết — UC refs** | UC-05-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module cảnh báo chưa có concurrency lock. Preview conflict là bước giảm rủi ro trước khi lock cứng.

Đọc nhanh cho dev: triển khai API preview conflict cho schedule. Điểm cần chốt khi code là API read-only; response có conflict_id, type, severity, impacted_target và suggested_action; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** xem trước conflict trước khi bật schedule
> **Để** operator biết schedule nào trùng device/account/time window trước khi gây tranh chấp

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI preview conflict theo device, account và time window trước khi schedule được bật.
- Hệ thống PHẢI trả severity và schedule liên quan cho từng conflict.
- Hệ thống PHẢI không mutate schedule, cron hoặc execution khi chỉ preview.
- Hệ thống PHẢI hiểu timezone/misfire policy đang áp dụng cho schedule.
- Hệ thống PHẢI giữ p95 phù hợp cho target lớn trong staging.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: API preview conflict cho schedule - luồng thành công**

```gherkin
Given operator soạn hoặc chỉnh schedule có target device/account/time window
When Operator gọi preview conflict trước khi lưu hoặc bật schedule
Then response trả conflict theo device/account/time window, severity và schedule liên quan mà không làm đổi trạng thái schedule
And telemetry ghi số conflict và latency; không tạo run hoặc dispatch
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-05-009
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given time window sai timezone, target không tồn tại hoặc caller không thuộc organization
When hệ thống xử lý request/event của DF-T-05-009
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Read-only và pagination ổn định**

```gherkin
Given dữ liệu liên quan thay đổi trong lúc client đang đọc hoặc phân trang
When client gọi lại cùng filter/sort của DF-T-05-009
Then hệ thống không tạo side-effect trong database
And pagination/sort vẫn ổn định, không mất hoặc nhân đôi bản ghi ngoài giới hạn đã document
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given schedule không có conflict, conflict nhiều lớp device/account, DST/timezone edge và target lớn
When chạy test tích hợp hoặc staging cho DF-T-05-009
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI chi tiết — DF-E-11.
- KHÔNG bao gồm thay đổi campaign execution engine — DF-E-04.
- KHÔNG bao gồm BI dashboard nâng cao ngoài KPI module — DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai conflict detector query schedule active trong cùng organization và time window.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-05-009: API read-only; response có conflict_id, type, severity, impacted_target và suggested_action.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] index theo organization, target_id, active window để query preview nhanh.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới API preview conflict cho schedule.
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
| TC-DF-T-05-009-01 | Positive | operator soạn hoặc chỉnh schedule có target device/account/time window | Operator gọi preview conflict trước khi lưu hoặc bật schedule | response trả conflict theo device/account/time window, severity và schedule liên quan mà không làm đổi trạng thái schedule |
| TC-DF-T-05-009-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | telemetry ghi số conflict và latency; không tạo run hoặc dispatch |
| TC-DF-T-05-009-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-05-009 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-05-009-04 | Negative | time window sai timezone, target không tồn tại hoặc caller không thuộc organization | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-05-009-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-05-009-06 | Edge | schedule không có conflict, conflict nhiều lớp device/account, DST/timezone edge và target lớn | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-05-009-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-05-002.

**Chặn:** DF-T-11-013.

**Phụ thuộc giữa Epic:** DF-E-04 cung cấp execution; DF-E-09 tiêu thụ domain event; DF-E-11 hiển thị UI.

**Rủi ro:**

- **R1 — Preview khác kết quả dispatch thật do timezone/misfire drift; giảm thiểu bằng dùng cùng resolver lịch.**
- **R2 — Response conflict quá chung chung khiến operator không sửa được; giảm thiểu bằng impacted_target và suggested_action.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-05-009` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — FR-05-02, FR-05-07.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
