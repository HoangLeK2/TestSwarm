# DF-T-07-013 — Account search / filter API

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-013 |
| **Title** | Account search / filter API |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-07-01, FR-07-14 |
| **Truy vết — UC refs** | UC-07-01 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Account inventory lớn cần search/filter có organization scope để tránh cross-tenant leak.

Đọc nhanh cho dev: triển khai API search/filter account. Điểm cần chốt khi code là response chỉ trả field an toàn, có cursor/stable sort và total/has_more nếu hỗ trợ; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** tìm/filter account theo platform, status, group, tag
> **Để** operator điều tra account nhanh trong inventory lớn

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI search/filter account theo username, platform, status, group và device link.
- Hệ thống PHẢI phân trang/sort ổn định khi account state thay đổi.
- Hệ thống PHẢI không trả credential plaintext hoặc session secret.
- Hệ thống PHẢI trả lỗi validate cho filter/sort không hỗ trợ.
- Hệ thống PHẢI giữ organization scope trên mọi query.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: API search/filter account - luồng thành công**

```gherkin
Given organization có nhiều account theo platform, status, group và device link
When operator hoặc UI gọi API search/filter account
Then response trả đúng account theo username/platform/status/group/device và pagination ổn định, không trả credential plaintext
And telemetry ghi filter/sort; không thay đổi account state
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-07-013
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given filter sai enum, device/group khác organization hoặc sort field không được hỗ trợ
When hệ thống xử lý request/event của DF-T-07-013
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Read-only và pagination ổn định**

```gherkin
Given dữ liệu liên quan thay đổi trong lúc client đang đọc hoặc phân trang
When client gọi lại cùng filter/sort của DF-T-07-013
Then hệ thống không tạo side-effect trong database
And pagination/sort vẫn ổn định, không mất hoặc nhân đôi bản ghi ngoài giới hạn đã document
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given kết quả rỗng, nhiều account đổi state trong lúc phân trang và filter kết hợp nhiều điều kiện
When chạy test tích hợp hoặc staging cho DF-T-07-013
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm login orchestration/captcha/2FA trên platform — trách nhiệm scenario.
- KHÔNG bao gồm vault production integration nếu chưa thuộc ticket hiện tại.
- KHÔNG bao gồm UI nâng cao — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai query builder whitelist filter/sort và organization scope bắt buộc.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-07-013: response chỉ trả field an toàn, có cursor/stable sort và total/has_more nếu hỗ trợ.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] index theo organization_id, platform, status, group_id, device_id, username.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới API search/filter account.
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
| TC-DF-T-07-013-01 | Positive | organization có nhiều account theo platform, status, group và device link | operator hoặc UI gọi API search/filter account | response trả đúng account theo username/platform/status/group/device và pagination ổn định, không trả credential plaintext |
| TC-DF-T-07-013-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | telemetry ghi filter/sort; không thay đổi account state |
| TC-DF-T-07-013-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-07-013 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-07-013-04 | Negative | filter sai enum, device/group khác organization hoặc sort field không được hỗ trợ | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-07-013-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-07-013-06 | Edge | kết quả rỗng, nhiều account đổi state trong lúc phân trang và filter kết hợp nhiều điều kiện | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-07-013-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001.

**Chặn:** DF-T-11-011.

**Phụ thuộc giữa Epic:** DF-E-04 tiêu thụ account resolution; DF-E-06 lưu account_id; DF-E-02 cung cấp device id cho device_accounts.

**Rủi ro:**

- **R1 — Search API lộ credential qua response tiện tay; giảm thiểu bằng DTO allowlist.**
- **R2 — Pagination lệch khi account state đổi; giảm thiểu bằng stable cursor/sort.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-07-013` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md) — FR-07-01, FR-07-14.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
