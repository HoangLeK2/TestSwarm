# DF-T-03-008 — Relay command dispatcher & session guard

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-008 |
| **Title** | Relay command dispatcher & session guard |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Done |
| **Labels** | `module:relay`, `layer:backend`, `layer:contract`, `type:feature`, `risk:auth`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-03-10, FR-03-11, FR-03-12, FR-03-13 |
| **Truy vết — UC refs** | UC-03-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Trước khi implement từng channel, relay cần dispatcher chung: nhận command envelope, xác thực session/device ownership, route tới channel đúng, gom result và timeout/error theo một chuẩn.

Đọc nhanh cho dev: triển khai relay command dispatcher và session guard. Điểm cần chốt khi code là result phải có command_id, status, started_at, finished_at, exit/error_code và channel; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** backend command được route đúng channel ADB/u2/scrcpy/STF
> **Để** mọi primitive device dùng chung session guard và error contract

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI route command tới ADB/u2/scrcpy/STF channel theo type.
- Hệ thống PHẢI kiểm tra session_id/device ownership trước khi thực thi.
- Hệ thống PHẢI timeout và cancel command an toàn.
- Hệ thống PHẢI trả structured result/error thống nhất.
- Hệ thống PHẢI không cho command chạy trên device DEAD/BUSY sai owner.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: relay command dispatcher và session guard - luồng thành công**

```gherkin
Given device có session hợp lệ và command có type ADB/u2/scrcpy/STF
When backend gửi command xuống relay dispatcher
Then dispatcher route đúng channel, kiểm tra session/device ownership và trả structured result/error
And timeout/cancel được xử lý an toàn, command không chạy trên device DEAD hoặc BUSY sai owner
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-008
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given session_id sai, device DEAD, command type không hỗ trợ hoặc payload sai schema
When hệ thống xử lý request/event của DF-T-03-008
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Timeout, retry và cleanup không để lại tài nguyên treo**

```gherkin
Given thao tác device/agent bị timeout, bị cancel hoặc mất kết nối tạm thời
When hệ thống xử lý retry/cleanup cho DF-T-03-008
Then command/process/session liên quan được đóng hoặc đánh dấu lỗi rõ ràng
And trạng thái cuối cùng có thể reconcile mà không cần thao tác thủ công mù
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given command timeout, cancel trong lúc chạy và nhiều command đến cùng một device
When chạy test tích hợp hoặc staging cho DF-T-03-008
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm implementation chi tiết từng channel — DF-T-03-010/011/012.
- KHÔNG bao gồm business ownership campaign/account — DF-E-04/7.
- KHÔNG bao gồm MCP tool wrapper — DF-E-10.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai dispatcher core dùng session guard trước khi gọi channel.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-008: result phải có command_id, status, started_at, finished_at, exit/error_code và channel.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] không cần DB riêng; audit/metric theo command_id.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới relay command dispatcher và session guard.
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
| TC-DF-T-03-008-01 | Positive | device có session hợp lệ và command có type ADB/u2/scrcpy/STF | backend gửi command xuống relay dispatcher | dispatcher route đúng channel, kiểm tra session/device ownership và trả structured result/error |
| TC-DF-T-03-008-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | timeout/cancel được xử lý an toàn, command không chạy trên device DEAD hoặc BUSY sai owner |
| TC-DF-T-03-008-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-008 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-008-04 | Negative | session_id sai, device DEAD, command type không hỗ trợ hoặc payload sai schema | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-008-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-008-06 | Edge | command timeout, cancel trong lúc chạy và nhiều command đến cùng một device | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-008-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-003, DF-T-03-005.

**Chặn:** DF-T-03-010, DF-T-03-011, DF-T-03-012, DF-T-10-005.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — Command chạy nhầm session owner; giảm thiểu bằng session guard trước channel dispatch.**
- **R2 — Channel lỗi làm mất response; giảm thiểu bằng structured error và timeout wrapper.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-008` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-10, FR-03-11, FR-03-12, FR-03-13.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
