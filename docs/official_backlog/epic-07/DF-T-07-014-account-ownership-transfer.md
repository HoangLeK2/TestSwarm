# DF-T-07-014 — Account ownership transfer

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-014 |
| **Title** | Account ownership transfer |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-07-14 |
| **Truy vết — UC refs** | UC-07-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Ownership transfer là lộ trình nhưng cần spec sớm vì có rủi ro cross-tenant và audit cao.

Đọc nhanh cho dev: triển khai chuyển quyền sở hữu account. Điểm cần chốt khi code là API phải trả per-account result nếu bulk và conflict rõ với active execution/binding; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** chuyển ownership account giữa user/group/tenant theo quy trình kiểm soát
> **Để** không phải xóa/tạo lại account khi tổ chức thay đổi phân công

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI chuyển owner account trong cùng organization theo quyền admin.
- Hệ thống PHẢI cập nhật quyền truy cập/account group liên quan theo policy.
- Hệ thống PHẢI chặn transfer khi account đang ở state không cho phép hoặc khác organization.
- Hệ thống PHẢI audit old_owner/new_owner/reason.
- Hệ thống PHẢI trả conflict rõ nếu account đang được execution dùng.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: chuyển quyền sở hữu account - luồng thành công**

```gherkin
Given account và người nhận thuộc cùng organization, account không ở state bị khóa chuyển giao
When Admin tổ chức gọi API transfer ownership cho account hoặc account group
Then owner mới nhận account, owner cũ mất quyền quản trị account và các group/link liên quan được cập nhật theo policy
And audit log và notification event ghi actor, old_owner, new_owner, account_id và reason
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-07-014
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given người nhận khác organization, account banned/locked, thiếu reason hoặc caller không có quyền
When hệ thống xử lý request/event của DF-T-07-014
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/idempotency không tạo dữ liệu trùng**

```gherkin
Given client retry cùng request hoặc hai request giống nhau đến gần như đồng thời
When Admin tổ chức gọi API transfer ownership cho account hoặc account group
Then hệ thống không tạo record/action trùng ngoài policy của DF-T-07-014
And response trả trạng thái cuối cùng đủ rõ để client tiếp tục vận hành
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given transfer nhiều account, transfer trong lúc campaign đang chạy và owner cũ bị disable
When chạy test tích hợp hoặc staging cho DF-T-07-014
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm login orchestration/captcha/2FA trên platform — trách nhiệm scenario.
- KHÔNG bao gồm vault production integration nếu chưa thuộc ticket hiện tại.
- KHÔNG bao gồm UI nâng cao — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai ownership service validate org/role/state và update ownership atomically.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-07-014: API phải trả per-account result nếu bulk và conflict rõ với active execution/binding.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] update owner_id/group membership trong transaction, audit after commit.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới chuyển quyền sở hữu account.
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
| TC-DF-T-07-014-01 | Positive | account và người nhận thuộc cùng organization, account không ở state bị khóa chuyển giao | Admin tổ chức gọi API transfer ownership cho account hoặc account group | owner mới nhận account, owner cũ mất quyền quản trị account và các group/link liên quan được cập nhật theo policy |
| TC-DF-T-07-014-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | audit log và notification event ghi actor, old_owner, new_owner, account_id và reason |
| TC-DF-T-07-014-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-07-014 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-07-014-04 | Negative | người nhận khác organization, account banned/locked, thiếu reason hoặc caller không có quyền | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-07-014-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-07-014-06 | Edge | transfer nhiều account, transfer trong lúc campaign đang chạy và owner cũ bị disable | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-07-014-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001.

**Chặn:** DF-T-11-011.

**Phụ thuộc giữa Epic:** DF-E-04 tiêu thụ account resolution; DF-E-06 lưu account_id; DF-E-02 cung cấp device id cho device_accounts.

**Rủi ro:**

- **R1 — Transfer làm mất quyền truy cập account/group liên quan; giảm thiểu bằng transaction và test permission after transfer.**
- **R2 — Transfer giữa lúc execution chạy gây binding không nhất quán; giảm thiểu bằng conflict policy với active execution.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-07-014` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md) — FR-07-14.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
