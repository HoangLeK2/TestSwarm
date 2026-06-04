# DF-T-03-005 — WebSocket/gRPC relay transport parity

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-005 |
| **Title** | WebSocket/gRPC relay transport parity |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P1 |
| **Story Points** | 8 |
| **Status** | Done |
| **Labels** | `module:relay`, `layer:backend`, `layer:contract`, `type:feature`, `risk:performance`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-03-07 |
| **Truy vết — UC refs** | UC-03-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module cam kết WebSocket và gRPC tương đương về ngữ nghĩa. Ticket này định nghĩa envelope, schema, error contract và bộ parity test để mỗi command mới phải pass trên cả hai transport.

Đọc nhanh cho dev: triển khai parity transport WebSocket/gRPC cho relay. Điểm cần chốt khi code là command envelope chung phải có command_id, device_id, session_id, timeout, payload và trace_id; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** agent dùng được cả WebSocket và gRPC với cùng ngữ nghĩa lệnh
> **Để** có đường lui khi một transport gặp sự cố mạng hoặc firewall

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI định nghĩa command envelope chung cho WS/gRPC.
- Hệ thống PHẢI config chọn transport per agent.
- Hệ thống PHẢI parity test cho cùng command qua hai transport.
- Hệ thống PHẢI chuyển transport không đổi behavior nghiệp vụ.
- Hệ thống PHẢI document cam kết tương đương — trace FR-03-07.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: parity transport WebSocket/gRPC cho relay - luồng thành công**

```gherkin
Given agent và backend hỗ trợ cả WebSocket và gRPC transport
When cùng một command được gửi qua hai transport trong parity test
Then response, error contract, timeout và behavior nghiệp vụ tương đương giữa hai transport
And parity test trở thành gate cho command mới
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-005
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given envelope thiếu field, transport config không hợp lệ hoặc command trả error khác schema
When hệ thống xử lý request/event của DF-T-03-005
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/idempotency không tạo dữ liệu trùng**

```gherkin
Given client retry cùng request hoặc hai request giống nhau đến gần như đồng thời
When cùng một command được gửi qua hai transport trong parity test
Then hệ thống không tạo record/action trùng ngoài policy của DF-T-03-005
And response trả trạng thái cuối cùng đủ rõ để client tiếp tục vận hành
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given chuyển transport khi agent reconnect, command timeout và payload lớn
When chạy test tích hợp hoặc staging cho DF-T-03-005
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm TLS gRPC hardening — DF-T-03-013.
- KHÔNG bao gồm command channel cụ thể — DF-T-03-010/011/012.
- KHÔNG bao gồm backend business route ownership — DF-E-02/4.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai transport adapter dùng chung dispatcher và mapping error.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-005: command envelope chung phải có command_id, device_id, session_id, timeout, payload và trace_id.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] không cần migration; chỉ config chọn transport per agent nếu chưa có.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới parity transport WebSocket/gRPC cho relay.
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
| TC-DF-T-03-005-01 | Positive | agent và backend hỗ trợ cả WebSocket và gRPC transport | cùng một command được gửi qua hai transport trong parity test | response, error contract, timeout và behavior nghiệp vụ tương đương giữa hai transport |
| TC-DF-T-03-005-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | parity test trở thành gate cho command mới |
| TC-DF-T-03-005-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-005 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-005-04 | Negative | envelope thiếu field, transport config không hợp lệ hoặc command trả error khác schema | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-005-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-005-06 | Edge | chuyển transport khi agent reconnect, command timeout và payload lớn | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-005-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-03-001.

**Chặn:** DF-T-03-008, DF-T-03-012, DF-T-03-013.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — Hai transport drift khiến bug chỉ xuất hiện ở một kênh; giảm thiểu bằng parity test bắt buộc.**
- **R2 — Config transport sai làm agent unreachable; giảm thiểu bằng fallback và startup validation.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-005` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-07.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
