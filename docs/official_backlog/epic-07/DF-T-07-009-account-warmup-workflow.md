# DF-T-07-009 — Account warmup workflow

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-009 |
| **Title** | Account warmup workflow |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-07-03 |
| **Truy vết — UC refs** | UC-07-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Warmup là lộ trình nhưng cần ticket để không trộn vào FSM hoặc round-robin core.

Đọc nhanh cho dev: triển khai workflow warmup account. Điểm cần chốt khi code là warmup run phải có run_id, account_id, state, step_summary và stop_reason; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** đưa account mới qua giai đoạn warmup có kiểm soát
> **Để** giảm rủi ro account mới bị checkpoint do dùng quá nhanh

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cho chạy warmup workflow cho account hoặc account group.
- Hệ thống PHẢI cập nhật warmup_state và last_warmup_at sau mỗi run.
- Hệ thống PHẢI dừng warmup khi phát hiện account banned/risk cao.
- Hệ thống PHẢI giới hạn tốc độ warmup để không vượt quota/platform guardrail.
- Hệ thống PHẢI ghi audit và metric cho warmup lifecycle.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: workflow warmup account - luồng thành công**

```gherkin
Given account mới hoặc ít hoạt động cần warmup trước khi chạy campaign chính
When operator hoặc schedule khởi chạy warmup workflow cho account/group
Then workflow tạo các bước warmup được phép, cập nhật warmup_state và dừng khi gặp tín hiệu ban/risk
And audit log ghi warmup start/finish/fail và metric success/fail theo platform
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-07-009
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given account banned/disabled, platform không hỗ trợ warmup hoặc workflow thiếu guardrail
When hệ thống xử lý request/event của DF-T-07-009
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/concurrency không tạo quyết định trùng**

```gherkin
Given scheduler retry cùng tick hoặc nhiều request chạm cùng resource gần như đồng thời
When operator hoặc schedule khởi chạy warmup workflow cho account/group
Then hệ thống chỉ ghi một quyết định cuối cùng hợp lệ cho cùng idempotency key/resource
And mọi quyết định defer/skip/fail đều có lý do truy vết được
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given nhiều account warmup song song, account bị ban giữa chừng và retry sau lỗi tạm thời
When chạy test tích hợp hoặc staging cho DF-T-07-009
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm login orchestration/captcha/2FA trên platform — trách nhiệm scenario.
- KHÔNG bao gồm vault production integration nếu chưa thuộc ticket hiện tại.
- KHÔNG bao gồm UI nâng cao — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai warmup orchestrator dùng scenario/dispatch guard và policy giới hạn hành động.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-07-009: warmup run phải có run_id, account_id, state, step_summary và stop_reason.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] lưu warmup_state/last_warmup_at/run history nếu chưa có.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới workflow warmup account.
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
| TC-DF-T-07-009-01 | Positive | account mới hoặc ít hoạt động cần warmup trước khi chạy campaign chính | operator hoặc schedule khởi chạy warmup workflow cho account/group | workflow tạo các bước warmup được phép, cập nhật warmup_state và dừng khi gặp tín hiệu ban/risk |
| TC-DF-T-07-009-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | audit log ghi warmup start/finish/fail và metric success/fail theo platform |
| TC-DF-T-07-009-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-07-009 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-07-009-04 | Negative | account banned/disabled, platform không hỗ trợ warmup hoặc workflow thiếu guardrail | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-07-009-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-07-009-06 | Edge | nhiều account warmup song song, account bị ban giữa chừng và retry sau lỗi tạm thời | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-07-009-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001.

**Chặn:** DF-T-11-011.

**Phụ thuộc giữa Epic:** DF-E-04 tiêu thụ account resolution; DF-E-06 lưu account_id; DF-E-02 cung cấp device id cho device_accounts.

**Rủi ro:**

- **R1 — Warmup biến thành automation chính vượt guardrail; giảm thiểu bằng action allowlist và quota riêng.**
- **R2 — Không dừng khi account bị ban làm tăng rủi ro platform; giảm thiểu bằng check state trước mỗi step.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-07-009` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md) — FR-07-03.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
