# DF-T-03-006 — Heartbeat & reconnect backoff

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-006 |
| **Title** | Heartbeat & reconnect backoff |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Done |
| **Labels** | `module:relay`, `layer:backend`, `layer:contract`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-03-05, FR-03-06 |
| **Truy vết — UC refs** | UC-03-04, UC-03-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Heartbeat là nguồn dữ liệu cho relay online/offline, còn reconnect loop giữ farm ổn định khi mạng chập chờn. Ticket này cũng tiêu thụ policy từ DF-T-02-006 để thống nhất cấu hình.

Đọc nhanh cho dev: triển khai heartbeat và reconnect backoff. Điểm cần chốt khi code là heartbeat payload phải có agent_id, relay_host, timestamp, device_count và transport status; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** agent gửi heartbeat và reconnect theo exponential backoff
> **Để** dashboard không báo offline giả và agent tự phục hồi khi mất kết nối tạm thời

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI gửi heartbeat theo chu kỳ cấu hình — trace FR-03-05.
- Hệ thống PHẢI heartbeat trễ không lập tức đánh offline nếu chưa vượt ngưỡng.
- Hệ thống PHẢI reconnect dùng exponential backoff có max interval — trace FR-03-06.
- Hệ thống PHẢI khôi phục device state sau reconnect thành công.
- Hệ thống PHẢI consume reconnect policy từ control plane.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: heartbeat và reconnect backoff - luồng thành công**

```gherkin
Given agent đã đăng ký và có kết nối relay/control plane
When agent gửi heartbeat định kỳ hoặc mất kết nối cần reconnect
Then heartbeat cập nhật last_seen; reconnect dùng exponential backoff và khôi phục device state sau khi kết nối lại
And policy từ control plane được consume; metric heartbeat latency/reconnect count được emit
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-006
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given policy backoff sai range, heartbeat thiếu agent id hoặc clock skew lớn
When hệ thống xử lý request/event của DF-T-03-006
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Reconnect, debounce và backpressure an toàn**

```gherkin
Given consumer mất kết nối hoặc xử lý chậm trong lúc event phát liên tục
When consumer reconnect hoặc backlog vượt ngưỡng
Then hệ thống áp dụng snapshot/replay/debounce theo contract của DF-T-03-006
And metric/log backpressure đủ để điều tra sự cố
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given backend tạm down, network chập chờn và agent reconnect nhiều lần
When chạy test tích hợp hoặc staging cho DF-T-03-006
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm alert notification cuối cùng — DF-E-09.
- KHÔNG bao gồm safe-mode backend — DF-E-01.
- KHÔNG bao gồm hot standby agent — lộ trình.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai heartbeat loop, reconnect scheduler và reconcile state sau reconnect.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-006: heartbeat payload phải có agent_id, relay_host, timestamp, device_count và transport status.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] last_seen/policy lưu trong registry hoặc config store hiện có.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới heartbeat và reconnect backoff.
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
| TC-DF-T-03-006-01 | Positive | agent đã đăng ký và có kết nối relay/control plane | agent gửi heartbeat định kỳ hoặc mất kết nối cần reconnect | heartbeat cập nhật last_seen; reconnect dùng exponential backoff và khôi phục device state sau khi kết nối lại |
| TC-DF-T-03-006-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | policy từ control plane được consume; metric heartbeat latency/reconnect count được emit |
| TC-DF-T-03-006-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-006 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-006-04 | Negative | policy backoff sai range, heartbeat thiếu agent id hoặc clock skew lớn | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-006-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-006-06 | Edge | backend tạm down, network chập chờn và agent reconnect nhiều lần | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-006-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-006, DF-T-03-004.

**Chặn:** DF-T-02-005, DF-T-02-015, DF-T-03-009.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — Heartbeat trễ bị đánh offline quá sớm; giảm thiểu bằng grace threshold cấu hình được.**
- **R2 — Reconnect đồng loạt gây thundering herd; giảm thiểu bằng jitter trong backoff.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-006` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-05, FR-03-06.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
