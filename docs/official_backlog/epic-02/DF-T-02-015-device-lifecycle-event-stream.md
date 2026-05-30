# DF-T-02-015 — Device lifecycle event stream (WS publish)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-015 |
| **Title** | Device lifecycle event stream (WS publish) |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:contract`, `type:feature`, `layer:test`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-01, FR-02-02, FR-02-03, FR-02-04, FR-02-13, FR-02-14 |
| **Truy vết — UC refs** | UC-02-02, UC-02-12, UC-02-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

FSM đã emit event nội bộ nhưng dashboard cần stream realtime đã auth để biết device online/offline, session claim/release, unpair, DEAD. Ticket này nối event bus sang WebSocket đã có auth ở DF-E-01.

Đọc nhanh cho dev: triển khai device lifecycle event stream qua WebSocket. Điểm cần chốt khi code là event schema phải có event_id, organization_id, device_id/session_id, state trước/sau và timestamp; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** nhận stream realtime về vòng đời device
> **Để** dashboard và notification cập nhật không cần polling nặng

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI publish event `device.state_changed`, `session.claimed`, `session.released`, `device.unpaired`.
- Hệ thống PHẢI chỉ gửi event thuộc organization của user.
- Hệ thống PHẢI batch/debounce khi nhiều device đổi state cùng lúc.
- Hệ thống PHẢI replay snapshot tối thiểu khi client reconnect.
- Hệ thống PHẢI metric backpressure khi consumer chậm.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: device lifecycle event stream qua WebSocket - luồng thành công**

```gherkin
Given user đã mở WebSocket hợp lệ và organization có device/session đang đổi state
When backend nhận state/session lifecycle event từ device/session service
Then stream publish `device.state_changed`, `session.claimed`, `session.released`, `device.unpaired` đúng organization
And consumer reconnect nhận snapshot/replay tối thiểu; metric backpressure tăng khi consumer chậm
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-02-015
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given WebSocket thiếu auth, user khác organization hoặc event payload thiếu device/session id
When hệ thống xử lý request/event của DF-T-02-015
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Reconnect, debounce và backpressure an toàn**

```gherkin
Given consumer mất kết nối hoặc xử lý chậm trong lúc event phát liên tục
When consumer reconnect hoặc backlog vượt ngưỡng
Then hệ thống áp dụng snapshot/replay/debounce theo contract của DF-T-02-015
And metric/log backpressure đủ để điều tra sự cố
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given nhiều device đổi state cùng lúc, client reconnect và consumer đọc chậm
When chạy test tích hợp hoặc staging cho DF-T-02-015
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm WebSocket auth foundation — DF-T-01-012.
- KHÔNG bao gồm notification rule xử lý alert — DF-E-09.
- KHÔNG bao gồm UI realtime rendering — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai publisher có debounce/batch, organization filter và replay snapshot tối thiểu.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-02-015: event schema phải có event_id, organization_id, device_id/session_id, state trước/sau và timestamp.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] không cần migration nếu dùng event bus hiện có; nếu có replay store phải có TTL rõ.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới device lifecycle event stream qua WebSocket.
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
| TC-DF-T-02-015-01 | Positive | user đã mở WebSocket hợp lệ và organization có device/session đang đổi state | backend nhận state/session lifecycle event từ device/session service | stream publish `device.state_changed`, `session.claimed`, `session.released`, `device.unpaired` đúng organization |
| TC-DF-T-02-015-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | consumer reconnect nhận snapshot/replay tối thiểu; metric backpressure tăng khi consumer chậm |
| TC-DF-T-02-015-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-02-015 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-02-015-04 | Negative | WebSocket thiếu auth, user khác organization hoặc event payload thiếu device/session id | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-02-015-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-02-015-06 | Edge | nhiều device đổi state cùng lúc, client reconnect và consumer đọc chậm | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-02-015-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-012, DF-T-02-002, DF-T-02-003.

**Chặn:** DF-T-09-001, DF-T-11-003.

**Phụ thuộc giữa Epic:** DF-E-09 subscribe event để phát alert; DF-E-11 hiển thị realtime.

**Rủi ro:**

- **R1 — Cross-tenant event leak qua stream; giảm thiểu bằng organization filter trước publish.**
- **R2 — Consumer chậm làm nghẽn publisher; giảm thiểu bằng backpressure metric và drop/debounce policy.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-02-015` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-01, FR-02-02, FR-02-03, FR-02-04, FR-02-13, FR-02-14.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
