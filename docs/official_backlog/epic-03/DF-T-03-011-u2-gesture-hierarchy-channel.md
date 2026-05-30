# DF-T-03-011 — u2 gesture & hierarchy channel

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-011 |
| **Title** | u2 gesture & hierarchy channel |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P0 |
| **Story Points** | 8 |
| **Status** | Backlog |
| **Labels** | `module:relay`, `layer:backend`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-03-11 |
| **Truy vết — UC refs** | UC-03-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

u2 là kênh chính cho gesture UI. Ticket này implement tap/swipe/scroll/input_text/key và hierarchy snapshot, reuse session để giảm chi phí khởi tạo.

Đọc nhanh cho dev: triển khai u2 gesture và hierarchy channel. Điểm cần chốt khi code là command/result phải thống nhất với dispatcher và scenario DSL; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** thực thi gesture và đọc hierarchy qua u2
> **Để** scenario và manual session thao tác UI ổn định trong dưới 2 giây

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI hỗ trợ tap/swipe/scroll/input_text/key qua u2 — trace FR-03-11.
- Hệ thống PHẢI gesture trả kết quả trong < 2 s ở điều kiện bình thường.
- Hệ thống PHẢI đọc hierarchy có cấu trúc và filter cơ bản.
- Hệ thống PHẢI reuse u2 session an toàn theo device.
- Hệ thống PHẢI lỗi u2 trả thông báo nghiệp vụ rõ.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: u2 gesture và hierarchy channel - luồng thành công**

```gherkin
Given device đã bootstrap u2/ATX, ONLINE và session hợp lệ
When scenario/runtime gửi gesture hoặc yêu cầu đọc hierarchy qua u2 channel
Then tap/swipe/scroll/input_text/key chạy trong ngưỡng; hierarchy trả cấu trúc có thể filter cơ bản
And u2 session được reuse an toàn theo device và lỗi trả mã nghiệp vụ rõ
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-011
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given gesture payload sai tọa độ/text, u2 session chết hoặc device không có bootstrap hợp lệ
When hệ thống xử lý request/event của DF-T-03-011
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Timeout, retry và cleanup không để lại tài nguyên treo**

```gherkin
Given thao tác device/agent bị timeout, bị cancel hoặc mất kết nối tạm thời
When hệ thống xử lý retry/cleanup cho DF-T-03-011
Then command/process/session liên quan được đóng hoặc đánh dấu lỗi rõ ràng
And trạng thái cuối cùng có thể reconcile mà không cần thao tác thủ công mù
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given gesture liên tiếp, hierarchy rất lớn và u2 reconnect giữa command
When chạy test tích hợp hoặc staging cho DF-T-03-011
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm AI vision/OCR extraction — DF-E-06.
- KHÔNG bao gồm scenario DSL mapping step — DF-E-04.
- KHÔNG bao gồm MCP wrapper — DF-E-10.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai u2 session manager, gesture executor và hierarchy reader có timeout.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-011: command/result phải thống nhất với dispatcher và scenario DSL.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] không cần DB riêng; artifact/hierarchy store thuộc DF-E-06 nếu cần persist.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới u2 gesture và hierarchy channel.
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
| TC-DF-T-03-011-01 | Positive | device đã bootstrap u2/ATX, ONLINE và session hợp lệ | scenario/runtime gửi gesture hoặc yêu cầu đọc hierarchy qua u2 channel | tap/swipe/scroll/input_text/key chạy trong ngưỡng; hierarchy trả cấu trúc có thể filter cơ bản |
| TC-DF-T-03-011-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | u2 session được reuse an toàn theo device và lỗi trả mã nghiệp vụ rõ |
| TC-DF-T-03-011-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-011 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-011-04 | Negative | gesture payload sai tọa độ/text, u2 session chết hoặc device không có bootstrap hợp lệ | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-011-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-011-06 | Edge | gesture liên tiếp, hierarchy rất lớn và u2 reconnect giữa command | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-011-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-03-002, DF-T-03-008.

**Chặn:** DF-T-04-002, DF-T-06-006.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — u2 session reuse sai device gây thao tác nhầm; giảm thiểu bằng binding session theo device serial.**
- **R2 — Hierarchy quá lớn làm response chậm; giảm thiểu bằng filter/size limit.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-011` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-11.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
