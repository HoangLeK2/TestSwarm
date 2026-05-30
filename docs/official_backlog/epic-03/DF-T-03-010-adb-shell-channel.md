# DF-T-03-010 — ADB shell command channel

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-010 |
| **Title** | ADB shell command channel |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:relay`, `layer:backend`, `layer:contract`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-03-10, FR-03-13 |
| **Truy vết — UC refs** | UC-03-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

ADB là kênh nền cho một số thao tác setup/diagnose mà u2 không phù hợp. Ticket này implement channel có guardrail chặt vì shell command có rủi ro cao.

Đọc nhanh cho dev: triển khai ADB shell command channel. Điểm cần chốt khi code là response phải phân biệt command failed, transport failed và validation failed; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** thực thi ADB shell command qua relay
> **Để** làm các thao tác mức thấp có timeout, exit code và audit rõ

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI thực thi command ADB với timeout cấu hình — trace FR-03-10.
- Hệ thống PHẢI trả stdout/stderr/exit code có cấu trúc.
- Hệ thống PHẢI allowlist command nguy hiểm hoặc require admin.
- Hệ thống PHẢI lỗi ADB không làm crash agent.
- Hệ thống PHẢI STF helper mức thấp được gọi có chủ đích và fail isolated — trace FR-03-13.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: ADB shell command channel - luồng thành công**

```gherkin
Given device ONLINE, session hợp lệ và command ADB nằm trong allowlist hoặc caller đủ quyền
When dispatcher gửi ADB shell command xuống agent
Then agent thực thi command với timeout và trả stdout/stderr/exit_code có cấu trúc
And ADB error không làm agent crash; STF helper cấp thấp fail isolated
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-010
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given command nguy hiểm không được allowlist, timeout sai range hoặc device mất ADB
When hệ thống xử lý request/event của DF-T-03-010
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Timeout, retry và cleanup không để lại tài nguyên treo**

```gherkin
Given thao tác device/agent bị timeout, bị cancel hoặc mất kết nối tạm thời
When hệ thống xử lý retry/cleanup cho DF-T-03-010
Then command/process/session liên quan được đóng hoặc đánh dấu lỗi rõ ràng
And trạng thái cuối cùng có thể reconcile mà không cần thao tác thủ công mù
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given stdout lớn, command timeout, ADB server restart và command trả non-zero exit code
When chạy test tích hợp hoặc staging cho DF-T-03-010
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm gesture UI chuẩn — DF-T-03-011.
- KHÔNG bao gồm stream scrcpy — DF-T-03-012.
- KHÔNG bao gồm business command không qua shell — DF-E-02 contract.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai ADB channel wrapper có timeout, allowlist/admin gate và process cleanup.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-010: response phải phân biệt command failed, transport failed và validation failed.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] không cần DB riêng; lưu command metric/audit nếu contract yêu cầu.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới ADB shell command channel.
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
| TC-DF-T-03-010-01 | Positive | device ONLINE, session hợp lệ và command ADB nằm trong allowlist hoặc caller đủ quyền | dispatcher gửi ADB shell command xuống agent | agent thực thi command với timeout và trả stdout/stderr/exit_code có cấu trúc |
| TC-DF-T-03-010-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | ADB error không làm agent crash; STF helper cấp thấp fail isolated |
| TC-DF-T-03-010-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-010 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-010-04 | Negative | command nguy hiểm không được allowlist, timeout sai range hoặc device mất ADB | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-010-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-010-06 | Edge | stdout lớn, command timeout, ADB server restart và command trả non-zero exit code | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-010-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-03-008.

**Chặn:** DF-T-02-012, DF-T-10-014.

**Phụ thuộc giữa Epic:** None.

**Rủi ro:**

- **R1 — Command nguy hiểm vượt allowlist; giảm thiểu bằng deny-by-default và admin gate.**
- **R2 — Process ADB treo làm nghẽn worker; giảm thiểu bằng timeout và cleanup.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-010` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-10, FR-03-13.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
