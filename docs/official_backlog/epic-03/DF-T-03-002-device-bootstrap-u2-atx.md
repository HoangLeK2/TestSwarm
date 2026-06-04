# DF-T-03-002 — Device bootstrap u2/ATX idempotent

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-002 |
| **Title** | Device bootstrap u2/ATX idempotent |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Done |
| **Labels** | `module:relay`, `layer:backend`, `layer:infra`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-03-02 |
| **Truy vết — UC refs** | UC-03-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Thiết bị Android mới không chắc đã có bundle runtime đúng version. Ticket này làm bootstrap idempotent: chỉ đẩy khi thiếu/sai version, không crash agent khi một device fail.

Đọc nhanh cho dev: triển khai bootstrap u2/ATX idempotent trên device. Điểm cần chốt khi code là bootstrap result phải có device serial, before_version, after_version, status và error_code; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** agent tự đẩy u2/ATX khi thiết bị mới cắm vào
> **Để** thiết bị sẵn sàng nhận lệnh mà không cần thao tác thủ công

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI detect version u2/ATX hiện có trên device.
- Hệ thống PHẢI đẩy bundle khi thiếu hoặc version không khớp.
- Hệ thống PHẢI bootstrap idempotent, chạy lại không phá trạng thái.
- Hệ thống PHẢI device sau bootstrap chuyển ONLINE qua FSM.
- Hệ thống PHẢI lỗi từng device không làm agent crash — trace FR-03-02.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: bootstrap u2/ATX idempotent trên device - luồng thành công**

```gherkin
Given device gắn vào host, có thể đã cài hoặc chưa cài đúng version u2/ATX
When agent chạy bootstrap cho một device
Then agent detect version, đẩy bundle khi thiếu/lệch version và đưa device về ONLINE sau bootstrap
And kết quả bootstrap per-device được publish cho FSM/control plane; lỗi một device không làm agent crash
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-002
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given device mất kết nối, bundle thiếu checksum hoặc version không hỗ trợ
When hệ thống xử lý request/event của DF-T-03-002
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Timeout, retry và cleanup không để lại tài nguyên treo**

```gherkin
Given thao tác device/agent bị timeout, bị cancel hoặc mất kết nối tạm thời
When hệ thống xử lý retry/cleanup cho DF-T-03-002
Then command/process/session liên quan được đóng hoặc đánh dấu lỗi rõ ràng
And trạng thái cuối cùng có thể reconcile mà không cần thao tác thủ công mù
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given chạy bootstrap lại nhiều lần, device đang ONLINE, device fail giữa lúc push bundle
When chạy test tích hợp hoặc staging cho DF-T-03-002
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm bulk bootstrap nhiều device — DF-T-03-014.
- KHÔNG bao gồm bundle release pipeline nâng cao — lộ trình.
- KHÔNG bao gồm logic scenario/campaign — DF-E-04.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai agent-side bootstrap runner idempotent có retry giới hạn.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-002: bootstrap result phải có device serial, before_version, after_version, status và error_code.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] không cần DB riêng ngoài event/state hiện có.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới bootstrap u2/ATX idempotent trên device.
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
| TC-DF-T-03-002-01 | Positive | device gắn vào host, có thể đã cài hoặc chưa cài đúng version u2/ATX | agent chạy bootstrap cho một device | agent detect version, đẩy bundle khi thiếu/lệch version và đưa device về ONLINE sau bootstrap |
| TC-DF-T-03-002-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | kết quả bootstrap per-device được publish cho FSM/control plane; lỗi một device không làm agent crash |
| TC-DF-T-03-002-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-002 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-002-04 | Negative | device mất kết nối, bundle thiếu checksum hoặc version không hỗ trợ | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-002-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-002-06 | Edge | chạy bootstrap lại nhiều lần, device đang ONLINE, device fail giữa lúc push bundle | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-002-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-03-001.

**Chặn:** DF-T-03-003, DF-T-03-011.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — Bootstrap chạy lại phá trạng thái device; giảm thiểu bằng detect version và idempotency test.**
- **R2 — Một device lỗi làm agent dừng toàn host; giảm thiểu bằng isolation per-device.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-002` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-02.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
