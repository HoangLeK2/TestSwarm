# DF-T-03-001 — Agent-boot CLI & host registration

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-001 |
| **Title** | Agent-boot CLI & host registration |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:relay`, `layer:backend`, `layer:infra`, `layer:contract`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-03-01 |
| **Truy vết — UC refs** | UC-03-01 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Agent là cầu nối outbound giữa cloud và thiết bị vật lý. Ticket đầu tiên chuẩn hóa CLI bootstrap host, cấu hình, đăng ký relay agent và lifecycle supervisor để không phải setup thủ công từng máy.

Đọc nhanh cho dev: triển khai CLI agent boot và host registration. Điểm cần chốt khi code là CLI phải có exit code và log message đủ rõ cho automation script; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** khởi chạy agent-boot trên host mới
> **Để** host tham gia fleet và xuất hiện trên dashboard trong dưới 60 giây

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp CLI khởi tạo agent với config org/relay endpoint.
- Hệ thống PHẢI đăng ký relay agent lên backend với host identity.
- Hệ thống PHẢI agent khởi động thành công trả exit code 0 — trace FR-03-01.
- Hệ thống PHẢI log startup thể hiện transport đang dùng.
- Hệ thống PHẢI agent xuất hiện trong relay registry trong < 60 s.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: CLI agent boot và host registration - luồng thành công**

```gherkin
Given host agent có config org/relay endpoint và credential hợp lệ
When Platform Engineer chạy CLI agent boot trên host mới
Then agent đăng ký host identity lên backend, exit code 0 và xuất hiện trong relay registry dưới 60 giây
And startup log ghi transport, relay endpoint và host id đã đăng ký, không log secret
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-001
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given thiếu config, credential sai hoặc backend không nhận organization/host identity
When hệ thống xử lý request/event của DF-T-03-001
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Timeout, retry và cleanup không để lại tài nguyên treo**

```gherkin
Given thao tác device/agent bị timeout, bị cancel hoặc mất kết nối tạm thời
When hệ thống xử lý retry/cleanup cho DF-T-03-001
Then command/process/session liên quan được đóng hoặc đánh dấu lỗi rõ ràng
And trạng thái cuối cùng có thể reconcile mà không cần thao tác thủ công mù
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given chạy lại CLI trên host đã đăng ký, restart agent và backend tạm mất kết nối
When chạy test tích hợp hoặc staging cho DF-T-03-001
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm bootstrap bundle vào thiết bị — DF-T-03-002.
- KHÔNG bao gồm per-agent key rotation — DF-T-03-013.
- KHÔNG bao gồm UI relay agents đầy đủ — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai registration endpoint/service nhận host identity và trạng thái transport.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-001: CLI phải có exit code và log message đủ rõ cho automation script.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] relay registry lưu host_id, organization_id, transport, last_seen.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới CLI agent boot và host registration.
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
| TC-DF-T-03-001-01 | Positive | host agent có config org/relay endpoint và credential hợp lệ | Platform Engineer chạy CLI agent boot trên host mới | agent đăng ký host identity lên backend, exit code 0 và xuất hiện trong relay registry dưới 60 giây |
| TC-DF-T-03-001-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | startup log ghi transport, relay endpoint và host id đã đăng ký, không log secret |
| TC-DF-T-03-001-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-001 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-001-04 | Negative | thiếu config, credential sai hoặc backend không nhận organization/host identity | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-001-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-001-06 | Edge | chạy lại CLI trên host đã đăng ký, restart agent và backend tạm mất kết nối | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-001-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001, DF-T-01-002.

**Chặn:** DF-T-03-002, DF-T-03-006.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — CLI thành công cục bộ nhưng backend không có registry; giảm thiểu bằng health check registry sau boot.**
- **R2 — Log startup lộ credential; giảm thiểu bằng redaction test.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-001` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-01.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
