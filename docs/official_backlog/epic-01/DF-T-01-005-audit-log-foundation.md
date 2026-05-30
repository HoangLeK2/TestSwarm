# DF-T-01-005 — Audit log foundation

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-005 |
| **Title** | Audit log foundation — bảng, schema sự kiện, append-only |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:db`, `type:feature`, `risk:legal-compliance`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-06 (audit invite/member), FR-01-12 (audit boundary access); open question đặc tả module về audit cho compliance |
| **Truy vết — UC refs** | UC-01-03, UC-01-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Open question của đặc tả module: *"Cơ chế audit ai đăng nhập, ai đổi mật khẩu, ai mời thành viên có cần đẩy ra một mục riêng cho compliance không?"* Trả lời cho M1: **có, ở mức foundation**. Lý do: nhiều khách hàng B2B yêu cầu evidence audit khi có incident; xây sớm rẻ hơn xây sau khi data đã chảy 6 tháng.

Ticket này build (1) bảng `audit_log` append-only với schema chuẩn — `event_type`, `actor_type` (user/system/device), `actor_id`, `org_id`, `target_type`, `target_id`, `ip`, `user_agent`, `metadata` JSONB, `created_at`; (2) helper `emit_audit_event(...)` cho các module khác gọi; (3) endpoint `GET /api/admin/audit-logs` cho admin tổ chức xem audit log của org mình (filter, pagination, không cho update/delete).

P1 vì không block release nhưng cần có trước khi onboard khách hàng đầu tiên. DF-T-01-002 (auth) và DF-T-01-003 (RBAC) đã reference emit_audit_event nên thực tế cần xong cùng release với DF-T-01-002.

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức
> **Tôi muốn** xem log mọi sự kiện auth, member, role change trong org của tôi
> **Để** điều tra incident bảo mật và đáp ứng yêu cầu compliance của khách hàng

> **Là** Platform Engineer
> **Tôi muốn** có helper `emit_audit_event` thống nhất
> **Để** mọi module trong codebase gọi cùng cách, không reinvent schema

## 4. Yêu cầu chức năng

- Hệ thống PHẢI bảng `audit_log` schema fix với cột: `id`, `event_type`, `actor_type`, `actor_id`, `org_id`, `target_type`, `target_id`, `ip`, `user_agent`, `metadata` JSONB, `created_at`.
- Hệ thống PHẢI append-only — DB không cho UPDATE/DELETE qua role app (chỉ INSERT). Có thể có DELETE qua admin DB role cho retention.
- Hệ thống PHẢI cung cấp `emit_audit_event(event_type, actor, target, metadata)` từ context request.
- Hệ thống PHẢI catalog event_type với prefix module: `auth.*`, `rbac.*`, `tenant.*`, `member.*`, `device.*` (cho DF-E-02 sau).
- Hệ thống PHẢI emit audit cho ít nhất các sự kiện sau (collaboration với ticket khác): `auth.login.success`, `auth.login.failed`, `auth.refresh`, `auth.refresh.replay_attempt`, `auth.logout`, `device_auth.failed`, `rbac.denied`, `tenant.cross_access_attempt`, `member.invited`, `member.role_changed`, `member.disabled`.
- Hệ thống PHẢI endpoint `GET /api/admin/audit-logs?event_type=&from=&to=&actor_id=` cho admin tổ chức (auth: admin, scope: org).
- Hệ thống PHẢI emit audit async (không block request) nhưng đảm bảo durability — dùng background queue với fallback DB write nếu queue down.
- Hệ thống PHẢI redact PII trong metadata: không lưu password, token, device key.
- Hệ thống NÊN có retention policy default 365 ngày (cấu hình per-org).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Login thành công emit audit**

```
Given alice login thành công
When event_type "auth.login.success" được emit
Then audit_log có entry mới với actor_type="user", actor_id=alice.id, org_id=acme.id, ip=<request_ip>, user_agent=<UA>, metadata={"jti":"..."} (KHÔNG có password hoặc token)
And entry xuất hiện trong DB trong < 2 s sau request
```

**AC-2: Admin xem audit log của org mình**

```
Given org acme có 50 audit entry trong 7 ngày qua
And bob là admin acme
When bob gọi GET /api/admin/audit-logs?from=2026-05-19&to=2026-05-26&page_size=20
Then response 200 với 20 entry, mỗi entry có đủ field
And tổng count trả 50
And entry của org khác (beta) KHÔNG xuất hiện
```

**AC-3: Append-only enforcement**

```
Given role app DB chỉ có quyền INSERT/SELECT trên audit_log
When code (giả định bị compromise) cố UPDATE audit_log SET event_type=..
Then DB từ chối với permission denied
And không có way nào từ API để modify entry
```

**AC-4: Async emit không block request**

```
Given request login thành công lúc T0
When server đo thời gian từ T0 đến response
Then response trả về trước khi audit entry được INSERT vào DB
And response time KHÔNG bị tăng > 5 ms do audit emit
And entry sau cùng vẫn xuất hiện trong DB trong < 2 s
```

**AC-5: PII redact trong metadata**

```
Given event "auth.login.failed" với attempt password "secret123"
When audit entry được emit
Then metadata KHÔNG chứa "secret123"
And không chứa raw token, không chứa device_key
And kiểm tra grep audit_log toàn DB sau test → không có pattern password
```

**AC-6: Queue down fallback**

```
Given background queue (Redis/RabbitMQ) tạm down
When sự kiện được emit
Then helper fallback sang INSERT trực tiếp DB (sync)
And response time tăng nhưng entry vẫn được lưu
And metric "audit.queue.fallback_count" tăng
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm audit cho mọi gesture/scenario step — too verbose, defer (open question đã ghi).
- KHÔNG bao gồm SIEM export (S3, Splunk) — defer Epic Notif & Analytics.
- KHÔNG bao gồm UI tìm kiếm audit — endpoint API ở ticket này; UI DF-E-11.
- KHÔNG bao gồm tamper-proof signing (HMAC chain) — đưa vào lộ trình sau compliance.
- KHÔNG bao gồm retention policy enforcement (cron xóa entry cũ) — defer ticket riêng, default 365 ngày chỉ là cấu hình.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/audit/service.py` — emit_audit_event, query API.
- [ ] Async emit qua Celery/RQ task; fallback sync write.
- [ ] PII redact filter.
- [ ] Endpoint `GET /api/admin/audit-logs`.

**Frontend** (`layer:frontend`)

- [ ] (Defer DF-E-11.)

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho /api/admin/audit-logs (filter, pagination).
- [ ] Event catalog markdown: `docs/audit/event-catalog.md` liệt kê event_type và metadata schema cho mỗi.

**Database / Migration** (`layer:db`)

- [ ] Bảng `audit_log` (id BIGSERIAL, event_type, actor_type, actor_id, org_id, target_type, target_id, ip INET, user_agent, metadata JSONB, created_at).
- [ ] Index (org_id, created_at DESC), (event_type, created_at), (actor_id, created_at).
- [ ] DB role `df_app` chỉ có INSERT/SELECT trên audit_log.
- [ ] DB role `df_admin` có DELETE (cho retention policy sau).

**Infra / DevOps** (`layer:infra`)

- [ ] Helm value `audit.async_enabled` (default true).
- [ ] Helm value `audit.retention_days` (default 365).
- [ ] Background worker deployment (Celery worker pod).

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "Audit".
- [ ] `docs/audit/event-catalog.md`.
- [ ] Runbook "Audit log query for incident".

**Test** (`layer:test`)

- [ ] Unit test emit_audit_event với mock queue.
- [ ] Integration test 6 AC.
- [ ] Test PII redact với grep DB sau 1000 emit random.
- [ ] Test concurrent emit (1000 events) không mất entry.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-005-01 | Positive | alice login | POST /api/auth/login đúng | audit_log có entry "auth.login.success" trong < 2 s |
| TC-DF-T-01-005-02 | Positive | bob admin acme, 50 entry trong 7 ngày | GET /api/admin/audit-logs?from=...&to=... | 200, danh sách đúng, scope org acme |
| TC-DF-T-01-005-03 | Negative | role app cố UPDATE audit_log | Query SQL UPDATE | DB permission denied |
| TC-DF-T-01-005-04 | Negative | carol (member acme) gọi /api/admin/audit-logs | GET endpoint | 403 FORBIDDEN_ROLE (do DF-T-01-003) |
| TC-DF-T-01-005-05 | Negative | Bob admin beta gọi audit-logs với param event_type của acme | GET /api/admin/audit-logs | 200 nhưng chỉ trả entry beta; entry acme không lộ |
| TC-DF-T-01-005-06 | Edge | Queue Redis down 30 s | 100 sự kiện emit | Tất cả entry vẫn lưu qua fallback sync; metric fallback_count = 100 |
| TC-DF-T-01-005-07 | Edge | Login fail với password chứa pattern "secret123" | Login | Grep audit_log không tìm thấy "secret123" trong metadata |
| TC-DF-T-01-005-08 | Edge | 10000 entry emit trong 60s | Bulk benchmark | Không mất entry; p99 emit (background) < 100 ms |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (runtime), DF-T-01-004 (org context để gán org_id audit).

**Chặn:** DF-T-01-002 (auth event emit cần audit có sẵn — coordinate same release), DF-T-01-009 (member event), DF-T-01-008 (audit metric integration).

**Phụ thuộc giữa Epic:** Mọi module DF-E-02-11 sẽ emit_audit_event cho sự kiện nghiệp vụ quan trọng (device pair/unpair, campaign create/delete, content export...).

**Rủi ro:**

- **R1 — Audit lost khi cả queue và DB fail.** Giảm thiểu: ghi local file backup last-chance, gồm fsync; alert sysadmin.
- **R2 — Audit table phình to nhanh.** Giảm thiểu: partition by month, retention 365 ngày, monitor disk.
- **R3 — Permission misconfigured cho phép UPDATE qua app role.** Giảm thiểu: CI check schema permission, integration test cố UPDATE phải fail.

**Phụ thuộc bên ngoài:** Redis hoặc RabbitMQ cho queue, Celery hoặc tương đương.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] 8 test case automation.
- [ ] `docs/modules/platform-runtime.md` mục Audit, `docs/audit/event-catalog.md`, runbook updated.
- [ ] CI check DB permission của role df_app pass.
- [ ] Telemetry: `audit.emit.count`, `audit.queue.fallback_count`, `audit.emit.latency_ms`.
- [ ] Performance: 10000 emit/min không drop entry, p99 < 100 ms async.
- [ ] PII redact test pass (grep clean).
- [ ] DBA review schema và retention policy.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — open question mục 10 về audit; FR-01-06 (audit member event).
- **Ma trận năng lực:** "Structured logging với request ID và trace ID" — Lộ trình; ticket này delivers một phần.
- **Nhóm người dùng:** Admin tổ chức.
- **Thuật ngữ:** Audit log.
- **Compliance refs:** SOC2 CC7.2 (audit), ISO 27001 A.12.4 (logging).
