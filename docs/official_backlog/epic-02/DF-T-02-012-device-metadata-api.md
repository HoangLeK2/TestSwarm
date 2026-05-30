# DF-T-02-012 — Device metadata API — context override & primitive contract

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-012 |
| **Title** | Device metadata API — context override & primitive contract |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:contract`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-02-05, FR-02-06, FR-02-07, FR-02-08, FR-02-09, FR-02-10, FR-02-15 |
| **Truy vết — UC refs** | UC-02-06, UC-02-07, UC-02-08, UC-02-09, UC-02-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Module Devices sở hữu contract control-plane cho primitive gesture/hierarchy/screenshot/stream và context override, còn execution thật nằm ở DF-E-03 relay. Ticket này tránh việc từng module tự định nghĩa payload khác nhau.

Đọc nhanh cho dev: triển khai metadata API và primitive contract cho device control plane. Điểm cần chốt khi code là OpenAPI phải mô tả rõ id type, merge rule, primitive capability và mã lỗi; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** có contract thống nhất cho primitive device và per-device context
> **Để** scenario/campaign gọi thiết bị đúng định danh, đúng override và không phụ thuộc implementation relay

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI định nghĩa metadata API trả đủ 4 loại id thiết bị — trace FR-02-15.
- Hệ thống PHẢI định nghĩa contract gesture/hierarchy/screenshot/stream ở control plane — trace FR-02-05..09.
- Hệ thống PHẢI lưu per-device context override và merge rule device override > scenario default — trace FR-02-10.
- Hệ thống PHẢI validate endpoint nhận đúng id type, sai id trả lỗi rõ.
- Hệ thống PHẢI ghi lại effective config dùng cho run để audit.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: metadata API và primitive contract cho device control plane - luồng thành công**

```gherkin
Given device đã đăng ký, có nhiều loại id và có context override ở device/scenario
When backend hoặc scenario runtime gọi metadata API để lấy id, primitive contract và effective context
Then response trả đúng db_id/device_serial/adb_serial/relay_serial, primitive capability và effective config theo rule device override > scenario default
And effective config được log/truy vết để execution audit dùng lại được
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-02-012
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given client truyền nhầm id type, device không thuộc organization hoặc override có schema sai
When hệ thống xử lý request/event của DF-T-02-012
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/idempotency không tạo dữ liệu trùng**

```gherkin
Given client retry cùng request hoặc hai request giống nhau đến gần như đồng thời
When backend hoặc scenario runtime gọi metadata API để lấy id, primitive contract và effective context
Then hệ thống không tạo record/action trùng ngoài policy của DF-T-02-012
And response trả trạng thái cuối cùng đủ rõ để client tiếp tục vận hành
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given device chưa có override, override một phần, hoặc primitive không được hỗ trợ bởi relay hiện tại
When chạy test tích hợp hoặc staging cho DF-T-02-012
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm thực thi ADB/u2/scrcpy thật — DF-E-03.
- KHÔNG bao gồm scenario DSL — DF-E-04.
- KHÔNG bao gồm UI editor override — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai metadata service resolve id type, capability và context override.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-02-012: OpenAPI phải mô tả rõ id type, merge rule, primitive capability và mã lỗi.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] lưu per-device context override có version/update timestamp để audit.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới metadata API và primitive contract cho device control plane.
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
| TC-DF-T-02-012-01 | Positive | device đã đăng ký, có nhiều loại id và có context override ở device/scenario | backend hoặc scenario runtime gọi metadata API để lấy id, primitive contract và effective context | response trả đúng db_id/device_serial/adb_serial/relay_serial, primitive capability và effective config theo rule device override > scenario default |
| TC-DF-T-02-012-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | effective config được log/truy vết để execution audit dùng lại được |
| TC-DF-T-02-012-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-02-012 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-02-012-04 | Negative | client truyền nhầm id type, device không thuộc organization hoặc override có schema sai | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-02-012-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-02-012-06 | Edge | device chưa có override, override một phần, hoặc primitive không được hỗ trợ bởi relay hiện tại | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-02-012-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-001, DF-T-02-003.

**Chặn:** DF-T-04-010, DF-T-06-003, DF-T-07-012.

**Phụ thuộc giữa Epic:** DF-E-03 thực thi primitive; DF-E-04/6/7 tiêu thụ context và artifact contract.

**Rủi ro:**

- **R1 — Nhầm id type khiến command đi sai device; giảm thiểu bằng schema tách field và validate id type.**
- **R2 — Effective config không được log làm khó audit execution; giảm thiểu bằng hook log bắt buộc.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-02-012` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-05, FR-02-06, FR-02-07, FR-02-08, FR-02-09, FR-02-10, FR-02-15.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
