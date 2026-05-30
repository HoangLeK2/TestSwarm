# DF-T-07-010 — Account bulk import / export CSV

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-010 |
| **Title** | Account bulk import / export CSV |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-07-02 |
| **Truy vết — UC refs** | UC-07-01 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

CRUD từng account không đủ cho vận hành thật. Ticket này chuẩn hóa file format và validation per row.

Đọc nhanh cho dev: triển khai bulk import/export account bằng CSV. Điểm cần chốt khi code là format CSV, per-row error_code và redaction rule phải được document; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** import/export nhiều account bằng CSV
> **Để** operator onboard hàng nghìn account nhanh và có báo cáo lỗi từng dòng

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI định nghĩa format CSV import/export account.
- Hệ thống PHẢI validate từng dòng và trả lỗi per-row, không chỉ lỗi tổng.
- Hệ thống PHẢI không import/export credential plaintext ngoài contract được phép.
- Hệ thống PHẢI hỗ trợ partial success có report rõ.
- Hệ thống PHẢI audit mọi lần import/export.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: bulk import/export account bằng CSV - luồng thành công**

```gherkin
Given operator có file CSV theo format chuẩn hoặc yêu cầu export account trong organization
When operator import CSV hoặc export danh sách account
Then import tạo/cập nhật account hợp lệ và trả kết quả per-row; export trả CSV đã redaction credential
And audit log ghi import/export, số dòng success/fail và file/report id
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-07-010
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given CSV thiếu cột bắt buộc, platform/status sai enum, row trùng hoặc account khác organization
When hệ thống xử lý request/event của DF-T-07-010
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/idempotency không tạo dữ liệu trùng**

```gherkin
Given client retry cùng request hoặc hai request giống nhau đến gần như đồng thời
When operator import CSV hoặc export danh sách account
Then hệ thống không tạo record/action trùng ngoài policy của DF-T-07-010
And response trả trạng thái cuối cùng đủ rõ để client tiếp tục vận hành
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given file rỗng, file rất lớn, một phần row lỗi và export có nhiều account
When chạy test tích hợp hoặc staging cho DF-T-07-010
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm login orchestration/captcha/2FA trên platform — trách nhiệm scenario.
- KHÔNG bao gồm vault production integration nếu chưa thuộc ticket hiện tại.
- KHÔNG bao gồm UI nâng cao — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai CSV parser/validator, import service per-row và export builder redaction-safe.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-07-010: format CSV, per-row error_code và redaction rule phải được document.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] bulk insert/update có transaction batch và unique key account/platform/org.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới bulk import/export account bằng CSV.
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
| TC-DF-T-07-010-01 | Positive | operator có file CSV theo format chuẩn hoặc yêu cầu export account trong organization | operator import CSV hoặc export danh sách account | import tạo/cập nhật account hợp lệ và trả kết quả per-row; export trả CSV đã redaction credential |
| TC-DF-T-07-010-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | audit log ghi import/export, số dòng success/fail và file/report id |
| TC-DF-T-07-010-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-07-010 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-07-010-04 | Negative | CSV thiếu cột bắt buộc, platform/status sai enum, row trùng hoặc account khác organization | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-07-010-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-07-010-06 | Edge | file rỗng, file rất lớn, một phần row lỗi và export có nhiều account | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-07-010-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001.

**Chặn:** DF-T-11-011.

**Phụ thuộc giữa Epic:** DF-E-04 tiêu thụ account resolution; DF-E-06 lưu account_id; DF-E-02 cung cấp device id cho device_accounts.

**Rủi ro:**

- **R1 — Một dòng lỗi làm mất toàn bộ import lớn; giảm thiểu bằng partial success/report.**
- **R2 — Export lộ credential/session data; giảm thiểu bằng redaction bắt buộc và test negative.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-07-010` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md) — FR-07-02.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
