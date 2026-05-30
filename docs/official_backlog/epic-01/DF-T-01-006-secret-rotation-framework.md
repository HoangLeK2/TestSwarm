# DF-T-01-006 — Secret rotation framework

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-006 |
| **Title** | Secret rotation framework cho JWT secret, device key và RELAY_API_KEY |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:infra`, `type:feature`, `risk:auth`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-01, FR-01-07 (giảm thiểu rủi ro rò); lộ trình đặc tả module mục 7 "Per-agent identity và rotation cho relay" |
| **Truy vết — UC refs** | UC-01-05 (Platform Engineer) |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 8 nêu rõ rủi ro: *"hiện nay tất cả các relay agent xác thực với backend bằng cùng một API key (RELAY_API_KEY). Chưa có cơ chế cấp key riêng cho từng agent và chưa có rotation định kỳ. Khi một key bị lộ, cách xử lý duy nhất là đổi key chung và khởi động lại toàn bộ agent."* Cùng vấn đề tồn tại với JWT signing secret — nếu secret rò, cách duy nhất hiện tại là đổi secret và invalidate toàn bộ session.

Ticket này build **framework rotation** — không phải full per-agent identity (đó là lộ trình dài hơn, scope một phần ở DF-T-03-013). Phạm vi M1: (1) hỗ trợ **multi-version secret** — JWT verify chấp nhận token ký bởi `secret-v1` hoặc `secret-v2` trong overlap window; (2) script rotate JWT secret không downtime; (3) khung lưu device key theo version cho phép rotate per-device sau (build chính trong DF-E-03); (4) runbook rotation chi tiết.

Lý do P1 (không P0): không block release, nhưng cần xong cùng release với DF-T-01-002 để team đã quen pattern rotation từ đầu. Trễ ticket này không break production nhưng để lại tech debt nguy hiểm.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** rotate JWT signing secret mà không gây session drop hàng loạt
> **Để** khi nghi rò secret, tôi có cách xử lý không phải đẩy ra incident page

> **Là** Platform Engineer
> **Tôi muốn** mỗi loại secret (JWT, relay key, device key) có quy trình rotation văn bản hóa và automation
> **Để** rotation định kỳ thực sự được thực hiện, không phải "sẽ làm khi cần"

## 4. Yêu cầu chức năng

- Hệ thống PHẢI hỗ trợ multi-version JWT secret — verify chấp nhận token ký bởi version active hoặc version `previous` trong overlap window (default 24h).
- Hệ thống PHẢI claim `kid` (key id) trong JWT header chỉ rõ version secret dùng ký.
- Hệ thống PHẢI lưu JWT secret theo version trong Kubernetes Secret hoặc Vault, key format `jwt-signing-key-v{N}`.
- Hệ thống PHẢI CLI command `df-admin rotate-jwt-secret` tạo version mới, đẩy lên secret store, gọi reload pod.
- Hệ thống PHẢI cấu hình `JWT_SECRET_ACTIVE_VERSION` qua env; runtime load active + previous theo `kid`.
- Hệ thống PHẢI khung schema device key versioning: bảng `device_keys` (device_id, key_hash, version, status, created_at, revoked_at) hỗ trợ multiple key active per device — trace FR-01-07.
- Hệ thống PHẢI runbook chi tiết cho 3 rotation: JWT secret, RELAY_API_KEY (shared), device key per-device.
- Hệ thống PHẢI emit audit event `secret.rotated` với `secret_type`, `version`, `actor`.
- Hệ thống NÊN có job định kỳ kiểm tra "tuổi" của secret active và gửi cảnh báo khi vượt ngưỡng (default 90 ngày JWT, 180 ngày relay key).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Rotate JWT secret không downtime**

```
Given runtime đang phục vụ với JWT secret v1; có 100 user đang có token cấp bởi v1
When Platform Engineer chạy "df-admin rotate-jwt-secret"
Then secret v2 được tạo và đẩy lên Kubernetes Secret
And pod reload config trong < 30 s (rolling)
And token cấp bởi v1 vẫn verify được trong overlap 24h
And token cấp sau rotation có kid=v2
And user không bị logout
```

**AC-2: Overlap window hết hạn — token cũ bị reject**

```
Given JWT secret v1 đã được rotate v2 25 giờ trước
And overlap window = 24h
When client gửi token có kid=v1
Then response 401 với code TOKEN_EXPIRED_KEY_REVOKED
And audit log entry "auth.kid_revoked_token_used"
```

**AC-3: Device key versioning cho phép rotate per-device**

```
Given device "df-001" có key v1 đang active
When Platform Engineer phát hành key v2 cho device df-001 qua API
Then bảng device_keys có 2 record: v1 (status=active), v2 (status=active)
And agent có thể auth bằng cả v1 và v2 trong overlap window
And sau khi agent confirm dùng v2, v1 chuyển status="revoked"
```

**AC-4: CLI rotate emit audit**

```
Given platform engineer eve có role admin platform (system-level, không phải org admin)
When eve chạy df-admin rotate-jwt-secret
Then audit_log có entry secret.rotated với actor=eve, secret_type="jwt-signing", version="v2", từ_version="v1"
```

**AC-5: Cảnh báo khi secret quá tuổi**

```
Given JWT secret v2 đã active 91 ngày
When job định kỳ "secret-age-check" chạy
Then alert "JWT signing key age > 90 days" được gửi vào kênh notify
And không cần action ngay nhưng có ticket auto-create reminder
```

**AC-6: Kubernetes Secret update không gây race**

```
Given 5 pod runtime đang chạy
When CLI rotate update Secret và trigger rollout
Then mỗi pod restart tuần tự, tại mọi thời điểm có ≥ 4 pod sẵn sàng
And không có request bị reject do "secret not loaded yet"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm Vault integration đầy đủ (HSM, dynamic secret) — đưa vào lộ trình sau.
- KHÔNG bao gồm full per-agent identity (cấp key riêng từng relay agent thay vì shared RELAY_API_KEY) — chỉ scaffold schema; full implementation ở DF-T-03-013.
- KHÔNG bao gồm UI quản lý secret — chỉ CLI ở M1.
- KHÔNG bao gồm database credential rotation — defer DevOps task.
- KHÔNG bao gồm rotate cho secret bên thứ ba (Stripe, OAuth provider) — không có ở M1.
- KHÔNG bao gồm zero-downtime rotate cho RELAY_API_KEY — relay agent phải restart sau khi rotate (sẽ giảm xuống ở DF-T-03-013).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/auth/secret_versioning.py` — load active + previous, verify theo kid.
- [ ] Cập nhật JWT issue và verify để dùng kid.
- [ ] Schema `device_keys` table (coordinate với DF-T-02-001).
- [ ] CLI `df-admin rotate-jwt-secret`, `df-admin rotate-relay-key`, `df-admin rotate-device-key DEVICE_ID`.
- [ ] Job định kỳ secret-age-check (Celery beat).

**Frontend** (`layer:frontend`)

- [ ] (Không có UI ở ticket này.)

**Contract / API** (`layer:contract`)

- [ ] Document JWT kid claim trong OpenAPI security scheme description.
- [ ] Mã lỗi TOKEN_EXPIRED_KEY_REVOKED.

**Database / Migration** (`layer:db`)

- [ ] Bảng `device_keys` (device_id, key_hash, version, status, created_at, revoked_at).
- [ ] Index (device_id, status, version).

**Infra / DevOps** (`layer:infra`)

- [ ] Kubernetes Secret schema với multiple key version.
- [ ] Helm value `auth.jwt_secret_overlap_hours` (default 24).
- [ ] Helm value `auth.jwt_secret_max_age_days` (default 90).
- [ ] Script `scripts/rotate-jwt-secret.sh` tích hợp với CLI.

**Documentation** (`layer:docs`)

- [ ] `docs/runbooks/secret-rotation.md` — quy trình 3 loại rotation.
- [ ] `docs/runbooks/secret-leak-incident.md` — quy trình khẩn cấp khi nghi rò.
- [ ] ADR-003: "JWT kid-based multi-version rotation".

**Test** (`layer:test`)

- [ ] Unit test verify token với kid khác nhau.
- [ ] Integration test rolling rotate (kind cluster).
- [ ] Test job secret-age-check trigger alert.
- [ ] Chaos test: rotate đúng lúc 100 request đang chạy → tất cả request hoàn tất OK.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-006-01 | Positive | Runtime với JWT secret v1, 100 user có token v1 | Chạy CLI rotate; chờ rollout xong; user gọi /api/me với token v1 | 200, token vẫn verify (trong overlap window) |
| TC-DF-T-01-006-02 | Positive | Sau rotate, user mới login | POST /api/auth/login | Token mới có kid=v2 |
| TC-DF-T-01-006-03 | Positive | Device df-001 có key v1; rotate v2 | Agent gọi runtime với v1 hoặc v2 | Cả hai pass; sau khi confirm v2 dùng, v1 status=revoked |
| TC-DF-T-01-006-04 | Negative | Overlap 24h đã qua; token v1 cũ | Gọi API | 401 TOKEN_EXPIRED_KEY_REVOKED |
| TC-DF-T-01-006-05 | Negative | Token có kid=v99 (không tồn tại) | Gọi API | 401 INVALID_SIGNATURE |
| TC-DF-T-01-006-06 | Edge | Rotate xảy ra ngay khi 100 request user-auth concurrent | Bắn 100 request; chạy rotate giữa chừng | 0 request fail; tất cả hoàn tất OK |
| TC-DF-T-01-006-07 | Edge | Secret v2 vừa được tạo nhưng pod chưa reload | Token mới cấp bởi v2 (qua pod đã reload) gọi API qua pod chưa reload | 200 nếu kid=v2 tồn tại trong cấu hình; nếu không, retry tự động qua pod khác (xử lý ở client) |
| TC-DF-T-01-006-08 | Edge | JWT secret age = 90 ngày + 1 phút | Job secret-age-check chạy | Alert được gửi; reminder ticket created |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (helm), DF-T-01-002 (JWT issue/verify cơ bản).

**Chặn:** DF-T-03-013 (secure handshake — cần khung versioned device key), DF-T-03-013 (per-agent identity full).

**Phụ thuộc giữa Epic:** Khung versioning cho relay key/device key sẽ được DF-E-03 dùng để hoàn thiện per-agent identity.

**Rủi ro:**

- **R1 — Rotate gây mass session drop.** Giảm thiểu: overlap window 24h + integration test concurrent.
- **R2 — Secret v1 và v2 cùng active gây nhầm tracking.** Giảm thiểu: log có kid trong mọi auth event.
- **R3 — Rollout pod fail giữa chừng, một pod có v1, một có v2.** Giảm thiểu: load cả active + previous → bất kỳ pod đều verify được cả hai.
- **R4 — Runbook không được thực thi định kỳ.** Giảm thiểu: job secret-age-check tạo reminder ticket tự động.

**Phụ thuộc bên ngoài:** Kubernetes ≥ 1.27 (Secret reload), Vault optional.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] 8 test case automation.
- [ ] Runbook `secret-rotation.md` và `secret-leak-incident.md` đã chạy thử trên staging (drill).
- [ ] ADR-003 merged.
- [ ] CLI có help text và đã test trên staging.
- [ ] Telemetry: `auth.kid_used_count` group by version, `secret.age_days` gauge per secret.
- [ ] Job secret-age-check đã chạy trên staging ≥ 1 lần và verify alert flow.
- [ ] Security review từ Platform Engineer + DBA.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — mục 7 lộ trình "Per-agent identity và rotation cho relay", mục 8 rủi ro RELAY_API_KEY và device key.
- **Đặc tả module (Agent Boot):** [`docs/official_docs/modules/03-agent-boot-and-relay.md`](../../official_docs/modules/03-agent-boot-and-relay.md) — mục 8 rủi ro shared API key.
- **Ma trận năng lực:** "Per-agent identity và rotation cho relay" — Lộ trình; ticket này delivers foundation.
- **Nhóm người dùng:** Platform Engineer.
- **Thuật ngữ:** Device key.
- **ADR liên quan:** ADR-003 sẽ tạo trong ticket.
