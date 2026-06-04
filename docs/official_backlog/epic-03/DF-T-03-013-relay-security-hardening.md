# DF-T-03-013 — Relay security hardening — secure handshake, gRPC TLS, per-agent identity

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-03-013 |
| **Title** | Relay security hardening — secure handshake, gRPC TLS, per-agent identity |
| **Type** | `type:feature` |
| **Epic** | DF-E-03 — Agent Boot & Relay |
| **Module** | DF-MOD-03 — Agent Boot & Relay |
| **Priority** | P2 |
| **Story Points** | 8 |
| **Status** | Done |
| **Labels** | `module:relay`, `layer:backend`, `layer:infra`, `layer:contract`, `type:feature`, `risk:auth`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-03-07 |
| **Truy vết — UC refs** | UC-03-07, UC-03-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module nêu hai rủi ro quan trọng: gRPC chưa TLS và API key tĩnh dùng chung. Ticket này harden relay path bằng secure handshake, TLS cho gRPC và per-agent key lifecycle tích hợp DF-T-01-006.

Đọc nhanh cho dev: triển khai secure handshake, TLS gRPC và per-agent identity. Điểm cần chốt khi code là handshake contract phải có agent_id, key_version, nonce/timestamp và error_code bảo mật; không mở rộng sang các mục đã ghi ở `Ngoài phạm vi`. Mọi API/event/schema mới phải giữ đúng `organization_id`, RBAC, idempotency khi có mutation và mã lỗi đã ghi trong ticket.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** relay agent có identity riêng và handshake bảo mật
> **Để** thu hồi hoặc rotate một agent mà không restart toàn fleet

Persona phụ: None.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI agent handshake xác thực danh tính relay riêng.
- Hệ thống PHẢI gRPC bật TLS bắt buộc hoặc qua overlay được document.
- Hệ thống PHẢI per-agent key có version, rotate và revoke.
- Hệ thống PHẢI thu hồi một agent không ảnh hưởng agent khác.
- Hệ thống PHẢI audit mọi handshake fail/success quan trọng.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: secure handshake, TLS gRPC và per-agent identity - luồng thành công**

```gherkin
Given relay agent có identity/key riêng và backend có secret rotation framework
When agent handshake với backend hoặc key được rotate/revoke
Then handshake xác thực agent riêng; gRPC chạy qua TLS/overlay được document; revoke một agent không ảnh hưởng agent khác
And audit log ghi handshake success/fail, key version và revoke/rotate action
```

**AC-2: Chặn sai quyền và sai organization**

```gherkin
Given request đến từ user/agent không có quyền hoặc tham chiếu resource khác organization
When request đi vào contract của DF-T-03-013
Then hệ thống trả 401/403/404 theo boundary đã định nghĩa
And response không lộ dữ liệu cross-tenant hoặc thông tin nhạy cảm
```

**AC-3: Validate input/state không hợp lệ**

```gherkin
Given key bị revoke, key version cũ, TLS config thiếu hoặc agent_id không khớp organization
When hệ thống xử lý request/event của DF-T-03-013
Then hệ thống từ chối với mã lỗi nghiệp vụ rõ ràng
And không ghi dữ liệu bán phần hoặc event gây hiểu nhầm cho consumer
```

**AC-4: Rotate/revoke identity không ảnh hưởng sai phạm vi**

```gherkin
Given một agent key bị rotate hoặc revoke
When agent cũ và agent khác cùng handshake lại
Then agent dùng key cũ bị từ chối với mã lỗi bảo mật rõ
And agent khác vẫn hoạt động bình thường nếu identity của nó hợp lệ
```

**AC-5: Boundary và quan sát vận hành**

```gherkin
Given rotate key trong lúc agent reconnect, nhiều agent handshake đồng thời và backend rollback config
When chạy test tích hợp hoặc staging cho DF-T-03-013
Then hệ thống giữ đúng KPI/giới hạn đã mô tả trong ticket và đặc tả module
And log/metric/audit đủ ngữ cảnh để dev/operator debug khi có failure
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm JWT user auth — DF-E-01.
- KHÔNG bao gồm mTLS đầy đủ với CA riêng — có thể tách nếu compliance yêu cầu.
- KHÔNG bao gồm hot standby/leader election — lộ trình.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Triển khai handshake verifier, key lifecycle integration và TLS config validation.
- [ ] Áp dụng RBAC, organization scope và state/session guard đúng boundary của ticket.
- [ ] Ghi audit/domain event/metric đúng như side effect trong AC-1 và AC-5.

**Frontend** (`layer:frontend`)

- [ ] Không build UI trong ticket này nếu header không có `layer:frontend`; UI chỉ consume contract ở Epic DF-E-11.
- [ ] Nếu generated client thay đổi, cập nhật consumer hoặc ghi rõ breaking change trong changelog.

**Contract / API** (`layer:contract`)

- [ ] Đặc tả request/response/event schema cho DF-T-03-013: handshake contract phải có agent_id, key_version, nonce/timestamp và error_code bảo mật.
- [ ] Cập nhật OpenAPI/event schema và document mã lỗi nghiệp vụ.
- [ ] Bổ sung ví dụ response thành công, lỗi validate và lỗi permission.

**Database / Migration** (`layer:db`)

- [ ] lưu per-agent key metadata/version/revoked_at qua framework DF-T-01-006.
- [ ] Kiểm tra index/constraint cho organization scope, idempotency và các filter chính nếu có.

**Infra / DevOps** (`layer:infra`)

- [ ] Chỉ thêm config/secret/metric dashboard khi AC hoặc requirement yêu cầu rõ.
- [ ] Nếu có job/worker/stream, khai báo retry, timeout, backpressure và alert metric tối thiểu.

**Documentation** (`layer:docs`)

- [ ] Cập nhật tài liệu kỹ thuật module liên quan tới secure handshake, TLS gRPC và per-agent identity.
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
| TC-DF-T-03-013-01 | Positive | relay agent có identity/key riêng và backend có secret rotation framework | agent handshake với backend hoặc key được rotate/revoke | handshake xác thực agent riêng; gRPC chạy qua TLS/overlay được document; revoke một agent không ảnh hưởng agent khác |
| TC-DF-T-03-013-02 | Positive | Luồng thành công đã chạy ít nhất một lần | Kiểm tra log/event/metric/consumer liên quan | audit log ghi handshake success/fail, key version và revoke/rotate action |
| TC-DF-T-03-013-03 | Negative | User/agent thiếu quyền hoặc resource khác organization | Gọi contract của DF-T-03-013 | Trả 401/403/404 đúng boundary, không lộ dữ liệu cross-tenant |
| TC-DF-T-03-013-04 | Negative | key bị revoke, key version cũ, TLS config thiếu hoặc agent_id không khớp organization | Gửi request/event không hợp lệ | Trả lỗi validate hoặc lỗi state rõ ràng, không ghi dữ liệu bán phần |
| TC-DF-T-03-013-05 | Edge | Dữ liệu rỗng, một bản ghi, và gần ngưỡng lớn nhất hợp lý | Chạy luồng chính với từng boundary | Kết quả đúng rule nghiệp vụ, không crash, không timeout ngoài KPI |
| TC-DF-T-03-013-06 | Edge | rotate key trong lúc agent reconnect, nhiều agent handshake đồng thời và backend rollback config | Chạy test tích hợp/staging mô phỏng boundary | Hệ thống vẫn giữ đúng contract và có log/metric để debug |
| TC-DF-T-03-013-07 | Resilience | Timeout/retry/concurrency hoặc reconnect xảy ra trong lúc xử lý | Lặp lại request/event/command theo idempotency hoặc retry policy | Không tạo dữ liệu trùng, không leak resource, trạng thái cuối cùng nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-002, DF-T-01-006, DF-T-03-005.

**Chặn:** DF-T-10-003.

**Phụ thuộc giữa Epic:** DF-E-01 cung cấp secret rotation framework; DF-E-10 dùng guardrail identity khi MCP điều khiển device.

**Rủi ro:**

- **R1 — Key chung bị lộ làm phải restart toàn fleet; giảm thiểu bằng per-agent key và revoke đơn lẻ.**
- **R2 — TLS config sai làm agent không kết nối được; giảm thiểu bằng startup validation và canary rollout.**

**Phụ thuộc bên ngoài:** None

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage >= 80% trên file thay đổi.
- [ ] Tất cả test case `DF-T-03-013` được map sang test tự động hoặc manual evidence.
- [ ] API contract/OpenAPI/event schema đã cập nhật nếu có thay đổi contract.
- [ ] Tài liệu kỹ thuật và tài liệu nghiệp vụ liên quan đã cập nhật.
- [ ] Telemetry/log/audit event cho path quan trọng đã có.
- [ ] Code review có >= 1 approve từ owner module.
- [ ] Release notes/changelog đã được cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-07.
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Template backlog:** [../_template.md](../_template.md).
