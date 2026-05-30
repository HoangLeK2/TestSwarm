# DF-T-02-014 — Device search & filter

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-014 |
| **Title** | Device search & filter |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:contract`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-02, FR-02-15 |
| **Truy vết — UC refs** | UC-02-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi fleet vượt vài trăm thiết bị, phân trang cơ bản không đủ. Ticket này chuẩn hóa search/filter theo serial, relay, state, group, tag, owner session và bảo đảm id type không bị nhầm.

Đọc nhanh cho dev: triển khai search và filter device. Điểm cần chốt khi code là API phải phân biệt device serial, ADB serial, relay serial và db id bằng field riêng; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** tìm và lọc device theo nhiều tiêu chí
> **Để** điều tra nhanh thiết bị trong fleet lớn

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI search theo device serial, ADB serial, relay serial và db id riêng field — trace FR-02-15.
- Hệ thống PHẢI filter theo state/group/tag/owner_type/relay host.
- Hệ thống PHẢI sort ổn định theo last_seen/name/state.
- Hệ thống PHẢI pagination không mất/nhân đôi record khi state đổi.
- Hệ thống PHẢI trả error rõ khi client truyền id type sai.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: search và filter device - luồng thành công**

```gherkin
Given fleet có nhiều device với serial, tag, group, owner_type và relay host khác nhau
When Fleet Operator gọi API search/filter theo serial/id/state/group/tag/owner_type/relay host
Then response trả đúng device theo filter, sort ổn định và pagination không mất/nhân đôi record
And telemetry ghi filter/sort được dùng; không thay đổi device/session state
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-02-014
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given client truyền id type sai field, sort không hỗ trợ hoặc filter trỏ sang resource khác organization
When hệ thống xử lý request/event của DF-T-02-014
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Read-only và pagination ổn định**

```gherkin
Given dữ liệu liên quan thay đổi trong lúc client đang đọc hoặc phân trang
When client gọi lại cùng filter/sort của DF-T-02-014
Then hệ thống không tạo side-effect trong database
And pagination/sort vẫn ổn định, không mất hoặc nhân đôi bản ghi ngoài giới hạn đã document
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given kết quả rỗng, nhiều device đổi state trong lúc phân trang và filter kết hợp nhiều điều kiện
When chạy test tích hợp hoặc staging cho DF-T-02-014
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm full-text fuzzy nâng cao — lộ trình.
- KHÔNG bao gồm UI saved filters — DF-E-11.
- KHÔNG bao gồm analytics theo lịch sử filter — DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai query builder có whitelist field, cursor hoặc stable sort, và organization scope bắt buộc.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-02-014: API phải phân biệt device serial, ADB serial, relay serial và db id bằng field riêng.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] index cho các filter chính và test query plan với fleet lớn.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới search và filter device.
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
| TC-DF-T-02-014-01 | Positive | fleet có nhiều device với serial, tag, group, owner_type và relay host khác nhau | Fleet Operator gọi API search/filter theo serial/id/state/group/tag/owner_type/relay host | response trả đúng device theo filter, sort ổn định và pagination không mất/nhân đôi record |
| TC-DF-T-02-014-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | telemetry ghi filter/sort được dùng; không thay đổi device/session state |
| TC-DF-T-02-014-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-02-014 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-02-014-04 | Negative | client truyền id type sai field, sort không hỗ trợ hoặc filter trỏ sang resource khác organization | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-02-014-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-02-014-06 | Edge | kết quả rỗng, nhiều device đổi state trong lúc phân trang và filter kết hợp nhiều điều kiện | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-02-014-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-007, DF-T-02-008.

**Chặn:** DF-T-11-003.

**Phụ thuộc giữa Epic:** Không.

**Rủi ro:**

- **R1 — Search nhầm serial giữa ADB/relay/db id; giảm thiểu bằng field riêng và lỗi validate rõ.**
- **R2 — Pagination offset bị lệch khi state đổi; giảm thiểu bằng stable sort/cursor.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-02-014` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-02, FR-02-15.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
