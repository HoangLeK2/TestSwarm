# DF-T-07-007 — Account variable resolution trong dispatch

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-007 |
| **Title** | Account variable resolution trong dispatch |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-07-07, FR-07-08, FR-07-11, FR-07-12 |
| **Truy vết — UC refs** | UC-07-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Scenario phải khai báo account intent rõ. Ticket này là chốt chặn để runtime inject account đúng và content/execution truy vết được account_id.

Đọc nhanh cho dev: triển khai resolve biến account trong dispatch. Điểm cần chốt khi code là resolver contract phải trả account_id, platform, binding_reason và error_code; không trả secret; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** resolve account intent tường minh khi dispatch scenario
> **Để** không còn fallback ngầm sang device primary account

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI resolve account variable trong scenario/campaign thành account_id cụ thể trước dispatch.
- Hệ thống PHẢI từ chối account banned/disabled/khác organization.
- Hệ thống PHẢI không trả credential plaintext trong response/log.
- Hệ thống PHẢI ghi effective account binding cho audit execution.
- Hệ thống PHẢI trả mã lỗi rõ khi không tìm được account phù hợp.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: resolve biến account trong dispatch - luồng thành công**

```gherkin
Given scenario/campaign tham chiếu account variable và account thuộc đúng organization
When execution runtime cần resolve account trước khi dispatch step
Then variable được resolve thành account_id hợp lệ, active và đúng scope; không trả credential plaintext
And effective account binding được log để audit execution và content trace
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-07-007
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given variable thiếu, account banned/disabled/khác organization hoặc group không có account khả dụng
When hệ thống xử lý request/event của DF-T-07-007
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/idempotency không tạo dữ liệu trùng**

```gherkin
Given client retry cùng request hoặc hai request giống nhau đến gần như đồng thời
When execution runtime cần resolve account trước khi dispatch step
Then hệ thống không tạo record/action trùng ngoài policy của DF-T-07-007
And response trả trạng thái cuối cùng đủ rõ để client tiếp tục vận hành
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given nhiều account match cùng variable, account đổi state trong lúc dispatch và fallback legacy bị tắt
When chạy test tích hợp hoặc staging cho DF-T-07-007
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm login orchestration/captcha/2FA trên platform — trách nhiệm scenario.
- KHÔNG bao gồm vault production integration nếu chưa thuộc ticket hiện tại.
- KHÔNG bao gồm UI nâng cao — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai account resolver tích hợp runtime DF-E-04 và validate ownership/state.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-07-007: resolver contract phải trả account_id, platform, binding_reason và error_code; không trả secret.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] query account/group/device_accounts có organization scope và lock nhẹ khi cần.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới resolve biến account trong dispatch.
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
| TC-DF-T-07-007-01 | Positive | scenario/campaign tham chiếu account variable và account thuộc đúng organization | execution runtime cần resolve account trước khi dispatch step | variable được resolve thành account_id hợp lệ, active và đúng scope; không trả credential plaintext |
| TC-DF-T-07-007-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | effective account binding được log để audit execution và content trace |
| TC-DF-T-07-007-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-07-007 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-07-007-04 | Negative | variable thiếu, account banned/disabled/khác organization hoặc group không có account khả dụng | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-07-007-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-07-007-06 | Edge | nhiều account match cùng variable, account đổi state trong lúc dispatch và fallback legacy bị tắt | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-07-007-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001.

**Chặn:** DF-T-04-010.

**Phụ thuộc giữa Epic:** DF-E-04 tiêu thụ account resolution; DF-E-06 lưu account_id; DF-E-02 cung cấp device id cho device_accounts.

**Rủi ro:**

- **R1 — Resolver tự fallback primary account làm sai authored scenario flow; giảm thiểu bằng yêu cầu binding_reason và lỗi rõ.**
- **R2 — Log lộ credential khi debug binding; giảm thiểu bằng redaction test.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-07-007` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md) — FR-07-07, FR-07-08, FR-07-11, FR-07-12.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
