# DF-T-02-010 — Capacity planning report

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-010 |
| **Title** | Capacity planning report |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-02, FR-02-13, FR-02-15 |
| **Truy vết — UC refs** | UC-02-02, UC-02-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi số thiết bị tăng, danh sách đơn lẻ không đủ để quyết định vận hành. Ticket này tổng hợp capacity theo organization, group, state, session owner, relay host và id loại thiết bị để giúp lên kế hoạch campaign/schedule.

Đọc nhanh cho dev: triển khai capacity planning report cho fleet. Điểm cần chốt khi code là API read-only, không tạo audit event mutation và không thay đổi session/device state; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** xem báo cáo capacity của fleet
> **Để** biết farm còn bao nhiêu thiết bị khả dụng cho campaign hoặc schedule sắp tới

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI tổng hợp số device theo state, group, relay host, owner_type.
- Hệ thống PHẢI phân biệt rõ db id, device serial, ADB serial, relay serial trong report — trace FR-02-15.
- Hệ thống PHẢI tính available capacity loại trừ device BUSY/DEAD.
- Hệ thống PHẢI cho phép filter theo group/tag/state.
- Hệ thống PHẢI response p95 dưới 1 giây với 1000 device/org.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: capacity planning report cho fleet - luồng thành công**

```gherkin
Given organization có device ở nhiều state, group, tag và relay host
When Fleet Operator gọi API capacity report với filter group/tag/state/relay host
Then response trả total/available/busy/dead theo breakdown đã chọn và phân biệt rõ db id, device serial, ADB serial, relay serial
And telemetry ghi latency, số device scan và filter được dùng; không ghi dữ liệu nghiệp vụ mới
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-02-010
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given filter sai enum, id type sai field hoặc filter trỏ sang resource khác organization
When hệ thống xử lý request/event của DF-T-02-010
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Read-only và pagination ổn định**

```gherkin
Given dữ liệu liên quan thay đổi trong lúc client đang đọc hoặc phân trang
When client gọi lại cùng filter/sort của DF-T-02-010
Then hệ thống không tạo side-effect trong database
And pagination/sort vẫn ổn định, không mất hoặc nhân đôi bản ghi ngoài giới hạn đã document
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given fleet 0/1/1000 device, nhiều state đổi trong lúc tính report và filter kết hợp nhiều chiều
When chạy test tích hợp hoặc staging cho DF-T-02-010
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm forecast dài hạn theo ngày/tuần — analytics DF-E-09.
- KHÔNG bao gồm UI biểu đồ nâng cao — DF-E-11.
- KHÔNG bao gồm auto-scale hoặc tự phân bổ device — DF-E-05/4.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai query aggregate theo state/group/tag/relay host và available capacity loại trừ BUSY/DEAD.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-02-010: API read-only, không tạo audit event mutation và không thay đổi session/device state.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] index phục vụ aggregate theo organization_id, state, group_id, tag và relay_host.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới capacity planning report cho fleet.
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
| TC-DF-T-02-010-01 | Positive | organization có device ở nhiều state, group, tag và relay host | Fleet Operator gọi API capacity report với filter group/tag/state/relay host | response trả total/available/busy/dead theo breakdown đã chọn và phân biệt rõ db id, device serial, ADB serial, relay serial |
| TC-DF-T-02-010-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | telemetry ghi latency, số device scan và filter được dùng; không ghi dữ liệu nghiệp vụ mới |
| TC-DF-T-02-010-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-02-010 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-02-010-04 | Negative | filter sai enum, id type sai field hoặc filter trỏ sang resource khác organization | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-02-010-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-02-010-06 | Edge | fleet 0/1/1000 device, nhiều state đổi trong lúc tính report và filter kết hợp nhiều chiều | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-02-010-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-007, DF-T-02-013.

**Chặn:** DF-T-05-005.

**Phụ thuộc giữa Epic:** DF-E-05 dùng capacity để throttle và preview conflict.

**Rủi ro:**

- **R1 — Nhầm lẫn 4 loại id làm operator đọc sai năng lực fleet; giảm thiểu bằng schema field rõ tên.**
- **R2 — Aggregate scan toàn bảng khi org lớn; giảm thiểu bằng index và test p95 với 1000 device/org.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-02-010` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-02, FR-02-13, FR-02-15.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
