# DF-T-05-007 — Fairness scheduler — chống starvation

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-007 |
| **Title** | Fairness scheduler — chống starvation |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Lập lịch |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | `Done` |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:contract`, `type:feature`, `persona:operator` |
| **Truy vết — FR refs** | FR-05-07, FR-05-12 |
| **Truy vết — UC refs** | UC-05-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Throttle per device/account có thể làm run bị defer. Nếu không có fairness, một schedule ít ưu tiên có thể không bao giờ chạy khi queue luôn đầy.

Đọc nhanh cho dev: triển khai fairness scheduler chống starvation. Điểm cần chốt khi code là selection result phải giải thích vì sao run/skip/defer để operator debug được; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** scheduler không để schedule bị trì hoãn mãi
> **Để** các campaign quan trọng không bị starvation khi fleet quá tải

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI chọn schedule đến hạn theo rule fairness, không chỉ theo thời điểm tạo.
- Hệ thống PHẢI tăng ưu tiên cho schedule hợp lệ bị chờ lâu nhưng vẫn tôn trọng quota/throttle.
- Hệ thống PHẢI ghi selected_reason/skipped_reason cho từng quyết định dispatch.
- Hệ thống PHẢI không dispatch schedule disabled/archived hoặc thiếu target.
- Hệ thống PHẢI có metric queue_age, starvation_count và dispatch_decision_count.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: fairness scheduler chống starvation - luồng thành công**

```gherkin
Given nhiều schedule đến hạn cùng lúc, cùng tranh device/account hoặc quota
When scheduler chọn schedule tiếp theo để dispatch
Then scheduler phân bổ lượt chạy công bằng theo organization/campaign/device/account và không để schedule hợp lệ bị đói lâu hơn ngưỡng cấu hình
And decision log/metric ghi queue_age, selected_reason, skipped_reason và fairness bucket
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-05-007
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given schedule archived/disabled, thiếu target hoặc vượt quota không được chọn
When hệ thống xử lý request/event của DF-T-05-007
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/concurrency không tạo quyết định trùng**

```gherkin
Given scheduler retry cùng tick hoặc nhiều request chạm cùng resource gần như đồng thời
When scheduler chọn schedule tiếp theo để dispatch
Then hệ thống chỉ ghi một quyết định cuối cùng hợp lệ cho cùng idempotency key/resource
And mọi quyết định defer/skip/fail đều có lý do truy vết được
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given backlog lớn sau downtime, nhiều tenant cùng tick và schedule retry liên tục
When chạy test tích hợp hoặc staging cho DF-T-05-007
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI chi tiết — DF-E-11.
- KHÔNG bao gồm thay đổi campaign execution engine — DF-E-04.
- KHÔNG bao gồm BI dashboard nâng cao ngoài KPI module — DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai selection algorithm có weight/round-robin hoặc aging rule chống starvation.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-05-007: selection result phải giải thích vì sao run/skip/defer để operator debug được.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] lưu queue metadata/last_selected_at nếu cần để tính fairness.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới fairness scheduler chống starvation.
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
| TC-DF-T-05-007-01 | Positive | nhiều schedule đến hạn cùng lúc, cùng tranh device/account hoặc quota | scheduler chọn schedule tiếp theo để dispatch | scheduler phân bổ lượt chạy công bằng theo organization/campaign/device/account và không để schedule hợp lệ bị đói lâu hơn ngưỡng cấu hình |
| TC-DF-T-05-007-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | decision log/metric ghi queue_age, selected_reason, skipped_reason và fairness bucket |
| TC-DF-T-05-007-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-05-007 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-05-007-04 | Negative | schedule archived/disabled, thiếu target hoặc vượt quota không được chọn | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-05-007-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-05-007-06 | Edge | backlog lớn sau downtime, nhiều tenant cùng tick và schedule retry liên tục | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-05-007-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-05-002.

**Chặn:** DF-T-11-013.

**Phụ thuộc giữa Epic:** DF-E-04 cung cấp execution; DF-E-09 tiêu thụ domain event; DF-E-11 hiển thị UI.

**Rủi ro:**

- **R1 — Fairness làm giảm throughput nếu weight sai; giảm thiểu bằng metric queue_age/throughput và config weight.**
- **R2 — Schedule bị defer không có lý do rõ; giảm thiểu bằng decision log bắt buộc.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-05-007` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — FR-05-07, FR-05-12.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
