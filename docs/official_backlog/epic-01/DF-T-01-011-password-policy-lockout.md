# DF-T-01-011 — Password policy & account lockout

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-011 |
| **Title** | Password policy (complexity, history) và account lockout chống brute force |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P1 |
| **Story Points** | 2 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:contract`, `type:feature`, `risk:auth` |
| **Truy vết — FR refs** | FR-01-01 (hardening) |
| **Truy vết — UC refs** | UC-01-01 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

DF-T-01-002 build JWT + login cơ bản với hash mật khẩu argon2 — đủ cho dev nhưng chưa đủ cho production. Trước khi onboard khách hàng đầu tiên, cần các guardrail bảo mật cơ bản: (1) mật khẩu phải đủ mạnh khi set (complexity rules); (2) tài khoản tự khóa khi bị brute force; (3) cấm dùng lại N mật khẩu gần nhất; (4) flow đổi mật khẩu cho user đã login; (5) cấm các mật khẩu thuộc breach list (top 10000 mật khẩu phổ biến).

Pain point bảo mật điển hình mà ticket này giải: brute force qua endpoint login. Nếu không có lockout, attacker có thể thử 1000 mật khẩu/giây qua API. Ticket áp dụng pattern phổ biến: sau N failed login (default 5) trong M phút (default 15), khóa account trong K phút (default 30) hoặc đến khi admin unlock.

P1 vì là hardening; DF-T-01-002 đã pass authn flow cơ bản nhưng ticket này phải close trước onboarding khách hàng thật.

## 3. Câu chuyện người dùng

> **Là** người vận hành
> **Tôi muốn** hệ thống yêu cầu mật khẩu đủ mạnh và tự khóa khi có dấu hiệu brute force
> **Để** tài khoản của tôi an toàn ngay cả khi attacker biết username

> **Là** Admin tổ chức
> **Tôi muốn** unlock account của thành viên khi họ bị khóa do quên mật khẩu
> **Để** không phải tạo lại account hoặc đợi auto-unlock

## 4. Yêu cầu chức năng

- Hệ thống PHẢI enforce password policy khi set/đổi mật khẩu: min 12 ký tự, ≥ 1 uppercase, ≥ 1 lowercase, ≥ 1 digit, ≥ 1 special — cấu hình được qua helm.
- Hệ thống PHẢI từ chối mật khẩu trong breach list (top 10000 phổ biến, file tham chiếu commit trong repo hoặc dùng `Have I Been Pwned` k-anon API).
- Hệ thống PHẢI lưu lịch sử ≥ 5 hash mật khẩu gần nhất; reject set lại mật khẩu trùng N gần đây.
- Hệ thống PHẢI track `failed_login_count` per user; sau 5 fail trong 15 phút → lock account trong 30 phút (auto-unlock) hoặc admin unlock manual.
- Hệ thống PHẢI reset `failed_login_count` về 0 khi login thành công.
- Hệ thống PHẢI endpoint `POST /api/me/change-password` body `{current_password, new_password}` — user-auth.
- Hệ thống PHẢI endpoint `POST /api/admin/members/{user_id}/unlock` — admin-auth, unlock account.
- Hệ thống PHẢI response khi account locked: 423 LOCKED với body `{"code":"ACCOUNT_LOCKED", "unlock_at": "..."}`.
- Hệ thống PHẢI emit audit event: `password.changed`, `password.policy_violation`, `account.locked`, `account.auto_unlocked`, `account.admin_unlocked`.
- Hệ thống PHẢI không khóa tài khoản admin cuối cùng của org (deadlock guard).
- Hệ thống PHẢI không tiết lộ "account locked" khi user chưa login (timing-safe; phải xác thực credential xong rồi mới check lock — hoặc trả 401 INVALID_CREDENTIALS cho cả 2 trường hợp).

> **Decision:** trả 423 LOCKED **chỉ khi** credential ĐÚNG nhưng account đang lock. Credential sai luôn trả 401 INVALID_CREDENTIALS — không lộ user tồn tại/đang lock.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Đặt mật khẩu đủ mạnh thành công**

```
Given alice đăng ký với password "Str0ng!Pass#123"
When backend validate
Then password pass tất cả rule
And hash lưu DB
```

**AC-2: Reject password yếu**

```
Given alice cố đặt password "password"
When backend validate
Then response 400 với code WEAK_PASSWORD
And body có list rule vi phạm: ["min_length", "missing_uppercase", "missing_digit", "in_breach_list"]
```

**AC-3: Account auto-lock sau 5 fail**

```
Given alice tồn tại
When attacker gửi 5 login với mật khẩu sai trong 5 phút
Then sau lần thứ 5, `users.failed_login_count` = 5, `locked_until` = now + 30min
When alice (chính chủ) login đúng mật khẩu trong 30 phút lock
Then response 423 LOCKED với unlock_at
And audit log "account.locked"
```

**AC-4: Auto-unlock sau 30 phút**

```
Given alice account đã bị lock 31 phút trước
When alice login đúng mật khẩu
Then response 200 với token; `failed_login_count` reset 0; `locked_until` clear
And audit log "account.auto_unlocked"
```

**AC-5: Admin unlock manual**

```
Given alice account đang lock
And bob admin acme
When bob POST /api/admin/members/{alice.id}/unlock
Then response 200; alice clear lock state
And audit log "account.admin_unlocked" với actor=bob
And alice login được ngay
```

**AC-6: Đổi password không được trùng 5 cũ**

```
Given alice đã dùng 5 password gần nhất P1..P5 (lưu hash)
When alice POST /api/me/change-password với new_password = P3
Then response 400 với code PASSWORD_REUSED
And audit log "password.policy_violation" với reason="reused"
```

**AC-7: Không khóa admin cuối**

```
Given acme chỉ còn 1 admin bob; ai đó bị brute force account bob
When 5 fail login với bob
Then bob KHÔNG bị lock (special guard)
And audit log "account.lock_skipped_last_admin"
And metric `auth.last_admin_lock_skipped_count` tăng — alert SRE
```

**AC-8: Credential sai trả 401 (không lộ lock state)**

```
Given alice account đang lock
When attacker gửi login với mật khẩu SAI
Then response 401 INVALID_CREDENTIALS (không 423)
And không tiết lộ alice tồn tại hay đang lock
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm MFA — đưa vào lộ trình sau.
- KHÔNG bao gồm CAPTCHA — defer; alternative chống brute force qua rate-limit IP (DF-T-01-013).
- KHÔNG bao gồm forgot password (email reset) — defer ticket frontend DF-E-11.
- KHÔNG bao gồm password strength meter UI — DF-E-11.
- KHÔNG bao gồm enforce expiration (force change every N days) — defer; NIST 800-63B khuyến nghị không expire arbitrary.
- KHÔNG bao gồm passkey / WebAuthn — đưa vào lộ trình sau.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/auth/password_policy.py` — validate rules.
- [ ] Breach list loader (file tĩnh hoặc HIBP k-anon).
- [ ] Module `device_farm/auth/lockout.py` — track failed_login_count, locked_until.
- [ ] Bảng `password_history` (user_id, password_hash, created_at).
- [ ] Endpoint `POST /api/me/change-password`.
- [ ] Endpoint `POST /api/admin/members/{user_id}/unlock`.
- [ ] Tích hợp vào DF-T-01-002 login flow.
- [ ] Last admin guard.

**Frontend** (`layer:frontend`)

- [ ] Trang đổi password (basic form) — coordinate với DF-T-01-010.
- [ ] Hiển thị error message rule cụ thể.
- [ ] Hiển thị error "Tài khoản tạm khóa, thử lại sau ..." khi 423.

**Contract / API** (`layer:contract`)

- [ ] Mã lỗi: WEAK_PASSWORD, PASSWORD_REUSED, ACCOUNT_LOCKED.
- [ ] OpenAPI spec cho 2 endpoint mới.

**Database / Migration** (`layer:db`)

- [ ] Cột trên `users`: `failed_login_count`, `locked_until`, `last_failed_login_at`.
- [ ] Bảng `password_history` (user_id, password_hash, created_at). Index (user_id, created_at DESC).
- [ ] Migration giữ ≤ 5 record per user (background cleanup).

**Infra / DevOps** (`layer:infra`)

- [ ] Helm value `auth.password.min_length` (12), `auth.password.complexity_rules`, `auth.password.history_size` (5).
- [ ] Helm value `auth.lockout.failed_threshold` (5), `auth.lockout.window_minutes` (15), `auth.lockout.duration_minutes` (30).
- [ ] Breach list file commit hoặc HIBP API key.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "Password & Lockout".
- [ ] Runbook "Account lockout incident".

**Test** (`layer:test`)

- [ ] Unit test policy với 20 password fixture.
- [ ] Integration test 8 AC.
- [ ] Test concurrent 5 failed login → đúng 1 lock event (không double).
- [ ] Test reset failed_count khi login thành công.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-011-01 | Positive | alice đặt password "Str0ng!Pass#123" | Set password | Pass, hash lưu DB |
| TC-DF-T-01-011-02 | Positive | alice login đúng | POST login | 200, failed_count reset 0 |
| TC-DF-T-01-011-03 | Positive | alice lock 31 phút trước | Login đúng | 200, auto-unlock |
| TC-DF-T-01-011-04 | Positive | bob admin unlock alice | POST /api/admin/members/{alice.id}/unlock | 200, alice unlock, audit entry |
| TC-DF-T-01-011-05 | Negative | password "password" | Set | 400 WEAK_PASSWORD với rule list |
| TC-DF-T-01-011-06 | Negative | alice fail login lần 6 | Login đúng sau 5 fail | 423 ACCOUNT_LOCKED |
| TC-DF-T-01-011-07 | Negative | alice cố đổi password thành P3 (dùng cách đây 2 lần) | POST change-password | 400 PASSWORD_REUSED |
| TC-DF-T-01-011-08 | Negative | account alice locked, attacker mật khẩu sai | Login sai | 401 INVALID_CREDENTIALS (KHÔNG 423) — chống lộ |
| TC-DF-T-01-011-09 | Edge | bob là admin cuối, brute force 5 lần | 5 fail login bob | bob KHÔNG lock, audit "last_admin_lock_skipped"; alert SRE |
| TC-DF-T-01-011-10 | Edge | 5 fail concurrent (race) | Bắn 5 request fail cùng lúc | Đúng 1 lock event; counter atomic; không skip |
| TC-DF-T-01-011-11 | Edge | Password trong breach list top 10000 | Set "Qwerty123!" | 400 WEAK_PASSWORD (in_breach_list) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-002 (login flow), DF-T-01-005 (audit).

**Chặn:** Onboard khách hàng production đầu tiên.

**Phụ thuộc giữa Epic:** Không.

**Rủi ro:**

- **R1 — Last admin guard bị abuse (brute force admin để denial-of-service).** Giảm thiểu: alert SRE khi guard kích hoạt; rate-limit IP riêng.
- **R2 — Breach list file phình to.** Giảm thiểu: dùng Bloom filter hoặc HIBP k-anon API.
- **R3 — Race condition concurrent fail login.** Giảm thiểu: atomic DB increment với row lock.

**Phụ thuộc bên ngoài:** Optional HIBP k-anon API.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85%.
- [ ] 11 test case automation.
- [ ] Security review từ Platform Engineer.
- [ ] Runbook lockout incident reviewed.
- [ ] Telemetry: `auth.password.weak_rejected`, `auth.lockout.count`, `auth.lockout.last_admin_skipped`.
- [ ] Audit log đầy đủ 5 sự kiện.
- [ ] Đã chạy thử brute force simulator trên staging, xác nhận lock kích hoạt đúng.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — FR-01-01 hardening.
- **Standards:** NIST 800-63B (digital identity guidelines), OWASP ASVS V2.
- **Nhóm người dùng:** Mọi persona vận hành.
