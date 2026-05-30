# DF-T-03-009 — Agent log shipper & operational telemetry

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-009 |
| **Title** | Agent log shipper & operational telemetry |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:relay`, `layer:backend`, `layer:infra`, `layer:test`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-03-05, FR-03-15 |
| **Truy vết — UC refs** | UC-03-08, UC-03-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

DF-E-01 dựng observability foundation, nhưng relay agent chạy ngoài cloud nên cần log shipper riêng. Ticket này chuẩn hóa log event, metric heartbeat/reconnect/dead ratio và input cho alert DF-E-09.

Đọc nhanh cho dev: triển khai agent log shipper và telemetry vận hành. Điểm cần chốt khi code là schema log/metric phải redaction-safe và có organization/agent/device context; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** ship log và metric quan trọng từ relay agent
> **Để** điều tra được agent offline, device DEAD và lỗi command mà không SSH vào host

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI ship structured log từ agent kèm request_id/session_id/device serial.
- Hệ thống PHẢI emit metric heartbeat latency, reconnect count, command failure.
- Hệ thống PHẢI publish domain event agent offline/dead ratio cho notification — trace FR-03-15.
- Hệ thống PHẢI không log secret/device key/plaintext credential.
- Hệ thống PHẢI buffer log khi mất mạng rồi flush có giới hạn.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: agent log shipper và telemetry vận hành - luồng thành công**

```gherkin
Given agent chạy command/heartbeat/reconnect và tạo structured log
When agent ship log/metric/event về backend hoặc observability sink
Then log có request_id/session_id/device serial; metric heartbeat latency, reconnect count, command failure được emit
And agent offline/dead ratio event được publish cho notification; log mất mạng được buffer có giới hạn
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-009
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given log chứa secret, payload quá lớn hoặc backend tạm không nhận
When hệ thống xử lý request/event của DF-T-03-009
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Reconnect, debounce và backpressure an toàn**

```gherkin
Given consumer mất kết nối hoặc xử lý chậm trong lúc event phát liên tục
When consumer reconnect hoặc backlog vượt ngưỡng
Then hệ thống áp dụng snapshot/replay/debounce theo contract của DF-T-03-009
And metric/log backpressure đủ để điều tra sự cố
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given mất mạng kéo dài, buffer đầy và lượng log tăng đột biến khi lỗi hàng loạt
When chạy test tích hợp hoặc staging cho DF-T-03-009
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm alert rule engine — DF-E-09.
- KHÔNG bao gồm full external log shipping SIEM — lộ trình.
- KHÔNG bao gồm UI relay log viewer — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai log shipper có redaction, buffer limit và retry policy.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-009: schema log/metric phải redaction-safe và có organization/agent/device context.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] nếu lưu tạm log local phải có retention/size limit.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới agent log shipper và telemetry vận hành.
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
| TC-DF-T-03-009-01 | Positive | agent chạy command/heartbeat/reconnect và tạo structured log | agent ship log/metric/event về backend hoặc observability sink | log có request_id/session_id/device serial; metric heartbeat latency, reconnect count, command failure được emit |
| TC-DF-T-03-009-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | agent offline/dead ratio event được publish cho notification; log mất mạng được buffer có giới hạn |
| TC-DF-T-03-009-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-009 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-009-04 | Negative | log chứa secret, payload quá lớn hoặc backend tạm không nhận | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-009-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-009-06 | Edge | mất mạng kéo dài, buffer đầy và lượng log tăng đột biến khi lỗi hàng loạt | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-009-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-008, DF-T-03-006.

**Chặn:** DF-T-09-001, DF-T-11-015.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — Log vô tình lộ device key/credential; giảm thiểu bằng redaction test.**
- **R2 — Buffer log đầy làm agent chậm hoặc hết disk; giảm thiểu bằng size cap và drop policy.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-009` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-05, FR-03-15.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
