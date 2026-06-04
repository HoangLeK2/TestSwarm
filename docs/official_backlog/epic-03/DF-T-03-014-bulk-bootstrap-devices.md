# DF-T-03-014 — Bulk bootstrap thiết bị mới trên một host

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-014 |
| **Title** | Bulk bootstrap thiết bị mới trên một host |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Done |
| **Labels** | `module:relay`, `layer:backend`, `layer:infra`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-03-14 |
| **Truy vết — UC refs** | UC-03-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Sau khi bootstrap đơn lẻ ổn định, vận hành cần một lệnh batch có giới hạn concurrency và báo cáo per-device. Ticket này hỗ trợ mở rộng fleet mà không làm nghẽn host hoặc làm agent crash.

Đọc nhanh cho dev: triển khai bulk bootstrap thiết bị mới trên host. Điểm cần chốt khi code là bulk result phải có batch_id và per-device status/retry_count/error_code; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** bootstrap hàng loạt thiết bị mới cắm vào host
> **Để** giảm công đăng ký và chuẩn bị device khi mở rộng fleet

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI bulk bootstrap chạy tuần tự hoặc song song có giới hạn — trace FR-03-14.
- Hệ thống PHẢI báo cáo kết quả per-device.
- Hệ thống PHẢI retry device fail theo policy có max attempts.
- Hệ thống PHẢI không block device đã ONLINE.
- Hệ thống PHẢI xuất summary để operator biết device nào cần can thiệp.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: bulk bootstrap thiết bị mới trên host - luồng thành công**

```gherkin
Given một host có nhiều device mới attach và agent đã có bootstrap runner
When Fleet Operator hoặc agent chạy bulk bootstrap cho danh sách device
Then bootstrap chạy tuần tự hoặc song song có giới hạn, trả kết quả per-device và bỏ qua device đã ONLINE
And summary cho operator nêu device thành công, fail, skipped và cần can thiệp
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-014
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given danh sách device có serial trùng, device khác host hoặc retry policy vượt max attempts
When hệ thống xử lý request/event của DF-T-03-014
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Timeout, retry và cleanup không để lại tài nguyên treo**

```gherkin
Given thao tác device/agent bị timeout, bị cancel hoặc mất kết nối tạm thời
When hệ thống xử lý retry/cleanup cho DF-T-03-014
Then command/process/session liên quan được đóng hoặc đánh dấu lỗi rõ ràng
And trạng thái cuối cùng có thể reconcile mà không cần thao tác thủ công mù
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given 50+ device attach cùng lúc, một số device fail giữa quá trình và agent restart giữa batch
When chạy test tích hợp hoặc staging cho DF-T-03-014
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm device procurement/asset tracking — ngoài scope.
- KHÔNG bao gồm campaign dispatch ngay sau bootstrap — DF-E-04/5.
- KHÔNG bao gồm UI wizard bulk onboarding — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai batch runner có concurrency limit, retry policy và resume/skipped logic.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-014: bulk result phải có batch_id và per-device status/retry_count/error_code.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] lưu batch summary nếu cần hiển thị/history; còn state device do DF-E-02 quản lý.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới bulk bootstrap thiết bị mới trên host.
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
| TC-DF-T-03-014-01 | Positive | một host có nhiều device mới attach và agent đã có bootstrap runner | Fleet Operator hoặc agent chạy bulk bootstrap cho danh sách device | bootstrap chạy tuần tự hoặc song song có giới hạn, trả kết quả per-device và bỏ qua device đã ONLINE |
| TC-DF-T-03-014-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | summary cho operator nêu device thành công, fail, skipped và cần can thiệp |
| TC-DF-T-03-014-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-014 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-014-04 | Negative | danh sách device có serial trùng, device khác host hoặc retry policy vượt max attempts | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-014-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-014-06 | Edge | 50+ device attach cùng lúc, một số device fail giữa quá trình và agent restart giữa batch | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-014-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-03-002, DF-T-03-003.

**Chặn:** DF-T-02-001.

**Phụ thuộc giữa Epic:** DF-E-02 nhận pair event sau khi device bootstrap xong.

**Rủi ro:**

- **R1 — Bulk chạy quá song song làm host quá tải; giảm thiểu bằng concurrency limit.**
- **R2 — Một device lỗi chặn cả batch; giảm thiểu bằng per-device isolation và summary.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-014` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-14.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
