# DF-T-07-012 — device_accounts link + primary flag

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-012 |
| **Title** | device_accounts link + primary flag |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P0 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-07-04 |
| **Truy vết — UC refs** | UC-07-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Dù canonical scenario phải khai báo account intent, device_accounts vẫn cần cho inventory, legacy template và vận hành theo thiết bị.

Đọc nhanh cho dev: triển khai liên kết device_accounts và primary flag. Điểm cần chốt khi code là API phải phân biệt link, unlink, set_primary và trả conflict rõ; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** gắn account với device và primary flag
> **Để** workflow legacy/thiết bị cụ thể biết account nào đi cùng device

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI link/unlink account với device trong cùng organization.
- Hệ thống PHẢI hỗ trợ primary flag và bảo đảm invariant một primary hợp lệ theo device/platform.
- Hệ thống PHẢI validate account state trước khi link hoặc set primary.
- Hệ thống PHẢI emit event khi binding thay đổi để runtime refresh.
- Hệ thống PHẢI audit mọi thay đổi device_accounts.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: liên kết device_accounts và primary flag - luồng thành công**

```gherkin
Given device và account thuộc cùng organization, cùng platform hoặc mapping được phép
When operator hoặc API link/unlink account với device và đặt primary flag
Then liên kết được lưu; mỗi device/platform chỉ có primary hợp lệ theo rule; account/device detail trả link chính xác
And audit log ghi link/unlink/set-primary và event để runtime refresh binding
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-07-012
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given device/account khác organization, account banned/disabled hoặc đặt nhiều primary cùng platform
When hệ thống xử lý request/event của DF-T-07-012
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/idempotency không tạo dữ liệu trùng**

```gherkin
Given client retry cùng request hoặc hai request giống nhau đến gần như đồng thời
When operator hoặc API link/unlink account với device và đặt primary flag
Then hệ thống không tạo record/action trùng ngoài policy của DF-T-07-012
And response trả trạng thái cuối cùng đủ rõ để client tiếp tục vận hành
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given link hàng loạt, đổi primary khi primary cũ đang dùng và unlink account đang bound với campaign
When chạy test tích hợp hoặc staging cho DF-T-07-012
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm login orchestration/captcha/2FA trên platform — trách nhiệm scenario.
- KHÔNG bao gồm vault production integration nếu chưa thuộc ticket hiện tại.
- KHÔNG bao gồm UI nâng cao — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai service validate ownership/platform/state và enforce primary invariant.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-07-012: API phải phân biệt link, unlink, set_primary và trả conflict rõ.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] bảng device_accounts unique theo org/device/account và partial unique primary theo device/platform.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới liên kết device_accounts và primary flag.
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
| TC-DF-T-07-012-01 | Positive | device và account thuộc cùng organization, cùng platform hoặc mapping được phép | operator hoặc API link/unlink account với device và đặt primary flag | liên kết được lưu; mỗi device/platform chỉ có primary hợp lệ theo rule; account/device detail trả link chính xác |
| TC-DF-T-07-012-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | audit log ghi link/unlink/set-primary và event để runtime refresh binding |
| TC-DF-T-07-012-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-07-012 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-07-012-04 | Negative | device/account khác organization, account banned/disabled hoặc đặt nhiều primary cùng platform | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-07-012-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-07-012-06 | Edge | link hàng loạt, đổi primary khi primary cũ đang dùng và unlink account đang bound với campaign | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-07-012-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001.

**Chặn:** DF-T-11-011.

**Phụ thuộc giữa Epic:** DF-E-04 tiêu thụ account resolution; DF-E-06 lưu account_id; DF-E-02 cung cấp device id cho device_accounts.

**Rủi ro:**

- **R1 — Nhiều primary làm runtime chọn account sai; giảm thiểu bằng unique constraint và validation service.**
- **R2 — Unlink account đang chạy execution gây lỗi dispatch; giảm thiểu bằng conflict check với active binding.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-07-012` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md) — FR-07-04.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
