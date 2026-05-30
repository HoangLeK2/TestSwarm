# DF-T-03-003 — ADB attach/detach watcher

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-003 |
| **Title** | ADB attach/detach watcher |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P0 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:relay`, `layer:backend`, `layer:test`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-03-03 |
| **Truy vết — UC refs** | UC-03-02, UC-03-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Attach/detach là input đầu tiên của toàn bộ FSM thiết bị. Nếu watcher bỏ sót event, control plane sẽ hiển thị device sai và campaign có thể dispatch vào thiết bị không còn tồn tại.

Đọc nhanh cho dev: triển khai watcher attach/detach ADB. Điểm cần chốt khi code là event attach/detach phải ổn định để DF-T-03-004 và DF-E-02 consume; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** agent phát hiện device cắm/rút qua ADB
> **Để** fleet state phản ánh thiết bị thật trong dưới 10 giây

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI watch `adb devices` hoặc event stream tương đương.
- Hệ thống PHẢI emit attach trong < 10 s.
- Hệ thống PHẢI emit detach trong < 10 s.
- Hệ thống PHẢI dedupe event flapping ngắn.
- Hệ thống PHẢI log đầy đủ serial, relay host, timestamp — trace FR-03-03.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: watcher attach/detach ADB - luồng thành công**

```gherkin
Given agent host đang chạy và ADB thấy device attach/detach
When ADB device list hoặc event stream thay đổi
Then agent emit attach/detach trong dưới 10 giây với serial, relay host và timestamp
And event flapping ngắn được dedupe và log đủ để debug
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-003
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given ADB trả output lỗi, serial rỗng hoặc device flapping vượt ngưỡng
When hệ thống xử lý request/event của DF-T-03-003
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Reconnect, debounce và backpressure an toàn**

```gherkin
Given consumer mất kết nối hoặc xử lý chậm trong lúc event phát liên tục
When consumer reconnect hoặc backlog vượt ngưỡng
Then hệ thống áp dụng snapshot/replay/debounce theo contract của DF-T-03-003
And metric/log backpressure đủ để điều tra sự cố
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given nhiều device attach cùng lúc, USB chập chờn và ADB daemon restart
When chạy test tích hợp hoặc staging cho DF-T-03-003
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm state transition rule chi tiết — DF-T-03-004.
- KHÔNG bao gồm device registry API — DF-T-02-001.
- KHÔNG bao gồm alert notification — DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai watcher loop có debounce và parser output ADB an toàn.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-003: event attach/detach phải ổn định để DF-T-03-004 và DF-E-02 consume.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] không cần DB riêng; publish event sang FSM/control plane.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới watcher attach/detach ADB.
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
| TC-DF-T-03-003-01 | Positive | agent host đang chạy và ADB thấy device attach/detach | ADB device list hoặc event stream thay đổi | agent emit attach/detach trong dưới 10 giây với serial, relay host và timestamp |
| TC-DF-T-03-003-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | event flapping ngắn được dedupe và log đủ để debug |
| TC-DF-T-03-003-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-003 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-003-04 | Negative | ADB trả output lỗi, serial rỗng hoặc device flapping vượt ngưỡng | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-003-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-003-06 | Edge | nhiều device attach cùng lúc, USB chập chờn và ADB daemon restart | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-003-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-03-001.

**Chặn:** DF-T-03-004, DF-T-02-001.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — Flapping tạo bão event và false DEAD; giảm thiểu bằng debounce window.**
- **R2 — Parser ADB sai làm mất device; giảm thiểu bằng fixture test nhiều format output.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-003` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-03.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
