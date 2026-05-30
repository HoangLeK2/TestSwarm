# DF-T-02-011 — Manual override — admin force-release & state reset

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-011 |
| **Title** | Manual override — admin force-release & state reset |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:contract`, `type:feature`, `risk:auth`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-03, FR-02-04, FR-02-13 |
| **Truy vết — UC refs** | UC-02-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Claim/release bình thường chỉ owner session được release. Nhưng trong vận hành thật có session treo do host chết, operator nghỉ ca, hoặc agent mất heartbeat. Ticket này tạo override an toàn cho admin với audit bắt buộc.

Đọc nhanh cho dev: triển khai manual override force-release và reset state. Điểm cần chốt khi code là override chỉ xử lý device/session, không can thiệp execution/campaign state; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức
> **Tôi muốn** force-release session hoặc reset state thiết bị khi có kẹt vận hành
> **Để** khôi phục fleet mà không phải sửa database thủ công

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI chỉ org-admin được force-release hoặc reset state.
- Hệ thống PHẢI force-release yêu cầu reason bắt buộc và ghi audit.
- Hệ thống PHẢI state reset chỉ cho phép từ DEAD/RECONNECTING/BUSY kẹt về CONNECTING/ONLINE theo rule.
- Hệ thống PHẢI không cho reset device thuộc organization khác.
- Hệ thống PHẢI emit event cho event stream/UI biết session bị override.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: manual override force-release và reset state - luồng thành công**

```gherkin
Given device thuộc organization và đang BUSY kẹt, DEAD hoặc RECONNECTING
When Admin tổ chức gọi API force-release hoặc reset state kèm reason bắt buộc
Then session bị release hoặc state được reset theo transition cho phép; response trả state trước/sau
And audit log và event lifecycle ghi rõ actor, reason, old_state, new_state, old_owner
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-02-011
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given người gọi không phải org-admin, thiếu reason, device khác organization hoặc state transition không được phép
When hệ thống xử lý request/event của DF-T-02-011
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Retry/idempotency không tạo dữ liệu trùng**

```gherkin
Given client retry cùng request hoặc hai request giống nhau đến gần như đồng thời
When Admin tổ chức gọi API force-release hoặc reset state kèm reason bắt buộc
Then hệ thống không tạo record/action trùng ngoài policy của DF-T-02-011
And response trả trạng thái cuối cùng đủ rõ để client tiếp tục vận hành
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given hai admin override cùng device gần như đồng thời hoặc device reconnect trong lúc override
When chạy test tích hợp hoặc staging cho DF-T-02-011
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm auto-recovery không cần admin — DF-T-02-004/005.
- KHÔNG bao gồm UI nút force-release — DF-E-11.
- KHÔNG bao gồm override campaign execution state — DF-E-04.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai service force-release/reset state có lock theo device và transition rule rõ.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-02-011: override chỉ xử lý device/session, không can thiệp execution/campaign state.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] ghi audit và event trong cùng transaction với state/session change.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới manual override force-release và reset state.
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
| TC-DF-T-02-011-01 | Positive | device thuộc organization và đang BUSY kẹt, DEAD hoặc RECONNECTING | Admin tổ chức gọi API force-release hoặc reset state kèm reason bắt buộc | session bị release hoặc state được reset theo transition cho phép; response trả state trước/sau |
| TC-DF-T-02-011-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | audit log và event lifecycle ghi rõ actor, reason, old_state, new_state, old_owner |
| TC-DF-T-02-011-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-02-011 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-02-011-04 | Negative | người gọi không phải org-admin, thiếu reason, device khác organization hoặc state transition không được phép | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-02-011-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-02-011-06 | Edge | hai admin override cùng device gần như đồng thời hoặc device reconnect trong lúc override | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-02-011-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-003, DF-T-02-002, DF-T-02-003.

**Chặn:** DF-T-02-013.

**Phụ thuộc giữa Epic:** DF-E-09 nhận event override để alert/audit.

**Rủi ro:**

- **R1 — Override làm mất dấu owner cũ; giảm thiểu bằng audit bắt buộc lưu old_owner và reason.**
- **R2 — Reset sai state che lỗi agent thật; giảm thiểu bằng whitelist transition từ DEAD/RECONNECTING/BUSY kẹt.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-02-011` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-03, FR-02-04, FR-02-13.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
