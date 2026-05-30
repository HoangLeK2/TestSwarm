# DF-T-09-015 — Notification inbox API — unread count & mark read

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-015 |
| **Title** | Notification inbox API — unread count & mark read |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:contract`, `type:feature`, `persona:operator` |
| **Truy vết — FR refs** | FR-09-03, FR-09-04, FR-09-05, FR-09-06, FR-09-15 |
| **Truy vết — UC refs** | UC-09-01, UC-09-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

DF-E-09 hiện có event ingest/rule/channel nhưng thiếu ticket riêng cho inbox API. Ticket này đóng gap FR-09-04/05/06 để frontend có contract hoàn chỉnh.

Đọc nhanh cho dev: triển khai notification inbox API, unread count và mark read. Điểm cần chốt khi code là API phải tách list/count/mark_read và response có read_at/unread_count mới nhất; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** xem inbox notification, unread count và mark read
> **Để** dashboard hiển thị notification cá nhân/tổ chức đúng và cập nhật trạng thái đọc

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI list notification inbox theo organization và recipient/persona.
- Hệ thống PHẢI trả unread count chính xác theo filter hiện hành.
- Hệ thống PHẢI mark read một hoặc nhiều notification theo cách idempotent.
- Hệ thống PHẢI phân trang ổn định khi notification mới đến.
- Hệ thống PHẢI không cho domain module ghi trực tiếp inbox record ngoài event/rule pipeline.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: notification inbox API, unread count và mark read - luồng thành công**

```gherkin
Given operator có notification trong organization, gồm read/unread và nhiều severity
When operator gọi API list inbox, unread count hoặc mark read
Then list trả notification đúng scope với pagination; unread count đúng; mark read cập nhật trạng thái idempotent
And event hoặc response giúp frontend cập nhật badge; audit chỉ ghi nếu mark read hàng loạt/quản trị theo policy
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-09-015
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given notification_id khác organization, caller thiếu quyền hoặc mark read payload sai
When hệ thống xử lý request/event của DF-T-09-015
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Idempotency và cập nhật trạng thái notification nhất quán**

```gherkin
Given cùng notification/action được retry hoặc nhiều client thao tác gần như đồng thời
When operator gọi API list inbox, unread count hoặc mark read
Then hệ thống không gửi/trạng thái hóa trùng ngoài policy đã định nghĩa
And response/event sau cùng phản ánh trạng thái mới nhất mà frontend có thể dùng
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given inbox rỗng, mark read notification đã đọc, nhiều notification mới đến trong lúc phân trang
When chạy test tích hợp hoặc staging cho DF-T-09-015
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI notification panel/dashboard — DF-E-11.
- KHÔNG bao gồm Prometheus/distributed tracing — DF-E-01.
- KHÔNG bao gồm BI warehouse chuyên sâu — ngoài phạm vi DF-E-09.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai inbox query service và mark-read mutation idempotent theo notification_id/user_id.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-09-015: API phải tách list/count/mark_read và response có read_at/unread_count mới nhất.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] index notifications theo organization_id, recipient/user/persona, read_at, created_at.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới notification inbox API, unread count và mark read.
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
| TC-DF-T-09-015-01 | Positive | operator có notification trong organization, gồm read/unread và nhiều severity | operator gọi API list inbox, unread count hoặc mark read | list trả notification đúng scope với pagination; unread count đúng; mark read cập nhật trạng thái idempotent |
| TC-DF-T-09-015-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | event hoặc response giúp frontend cập nhật badge; audit chỉ ghi nếu mark read hàng loạt/quản trị theo policy |
| TC-DF-T-09-015-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-09-015 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-09-015-04 | Negative | notification_id khác organization, caller thiếu quyền hoặc mark read payload sai | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-09-015-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-09-015-06 | Edge | inbox rỗng, mark read notification đã đọc, nhiều notification mới đến trong lúc phân trang | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-09-015-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-001, DF-T-09-002.

**Chặn:** DF-T-11-014.

**Phụ thuộc giữa Epic:** DF-E-11 tiêu thụ API; mọi domain Epic phát event qua DF-E-09.

**Rủi ro:**

- **R1 — Unread count lệch khi mark read đồng thời với notification mới; giảm thiểu bằng transaction hoặc query count sau update.**
- **R2 — Mark read cross-tenant làm mất notification của tenant khác; giảm thiểu bằng organization + recipient guard.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-09-015` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — FR-09-03, FR-09-04, FR-09-05, FR-09-06, FR-09-15.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
