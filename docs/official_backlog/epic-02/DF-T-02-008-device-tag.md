# DF-T-02-008 — Device tag — gắn tag tự do

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-008 |
| **Title** | Device tag — gắn tag tự do |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P2 |
| **Story Points** | 2 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-02, FR-02-11 |
| **Truy vết — UC refs** | UC-02-02, UC-02-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Device group phù hợp cho dispatch theo lô, nhưng vận hành hằng ngày vẫn cần tag nhẹ để đánh dấu project, vị trí rack, trạng thái kiểm tra, hoặc nhãn tạm thời. Ticket này thêm tag tự do có organization scope và filter cơ bản trong fleet view.

Đọc nhanh cho dev: triển khai tag device theo organization. Điểm cần chốt khi code là contract tag phải tách rõ add/remove/list/filter và không thay đổi group membership; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** gắn tag linh hoạt cho thiết bị
> **Để** lọc và gom thiết bị theo dự án/nhãn vận hành mà không phải tạo group cứng

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI lưu tag theo organization và không cho trùng key/value bất hợp lý — trace FR-02-02.
- Hệ thống PHẢI cho phép gắn/gỡ nhiều tag trên một device mà không ảnh hưởng group membership — trace FR-02-11.
- Hệ thống PHẢI trả tag trong fleet list và device detail.
- Hệ thống PHẢI audit thao tác gắn/gỡ tag.
- Hệ thống PHẢI filter fleet theo tag chính xác và phân trang ổn định.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: tag device theo organization - luồng thành công**

```gherkin
Given device thuộc đúng organization và tag key/value hợp lệ
When Fleet Operator gọi API gắn hoặc gỡ tag trên device
Then tag được lưu đúng device, trả về trong fleet list và device detail, filter theo tag trả đúng tập device
And audit log ghi actor, device_id, tag thay đổi và request_id
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-02-008
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given tag key/value rỗng, vượt giới hạn độ dài, trùng bất hợp lý hoặc device thuộc organization khác
When hệ thống xử lý request/event của DF-T-02-008
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/idempotency không tạo dữ liệu trùng**

```gherkin
Given client retry cùng request hoặc hai request giống nhau đến gần như đồng thời
When Fleet Operator gọi API gắn hoặc gỡ tag trên device
Then hệ thống không tạo record/action trùng ngoài policy của DF-T-02-008
And response trả trạng thái cuối cùng đủ rõ để client tiếp tục vận hành
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given device có nhiều tag, filter kết hợp state/group/tag và danh sách device đang phân trang
When chạy test tích hợp hoặc staging cho DF-T-02-008
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm bulk edit tag trên nhiều device — xử lý sau trong DF-E-11 UI.
- KHÔNG bao gồm tag policy nâng cao hoặc taxonomy bắt buộc — lộ trình vận hành.
- KHÔNG bao gồm group action fan-out — DF-T-02-009.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai service gắn/gỡ tag idempotent, validate uniqueness theo organization và device.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-02-008: contract tag phải tách rõ add/remove/list/filter và không thay đổi group membership.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] bảng hoặc cột tag có index cho organization_id, device_id, key/value và filter.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới tag device theo organization.
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
| TC-DF-T-02-008-01 | Positive | device thuộc đúng organization và tag key/value hợp lệ | Fleet Operator gọi API gắn hoặc gỡ tag trên device | tag được lưu đúng device, trả về trong fleet list và device detail, filter theo tag trả đúng tập device |
| TC-DF-T-02-008-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | audit log ghi actor, device_id, tag thay đổi và request_id |
| TC-DF-T-02-008-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-02-008 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-02-008-04 | Negative | tag key/value rỗng, vượt giới hạn độ dài, trùng bất hợp lý hoặc device thuộc organization khác | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-02-008-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-02-008-06 | Edge | device có nhiều tag, filter kết hợp state/group/tag và danh sách device đang phân trang | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-02-008-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-001.

**Chặn:** DF-T-02-014.

**Phụ thuộc giữa Epic:** DF-E-11 tiêu thụ tag để filter UI fleet.

**Rủi ro:**

- **R1 — Tag bị dùng thay group làm sai fan-out; giảm thiểu bằng rule không cho tag thay đổi group membership.**
- **R2 — Filter theo tag chậm khi fleet lớn; giảm thiểu bằng index theo organization_id + key/value.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-02-008` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-02, FR-02-11.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
