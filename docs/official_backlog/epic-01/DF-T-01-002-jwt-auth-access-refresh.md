# DF-T-01-002 — JWT auth (access + refresh token) + device-auth

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-002 |
| **Title** | JWT auth (access + refresh) cho user và device-auth qua device key |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:contract`, `layer:db`, `type:feature`, `risk:auth`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-01, FR-01-02, FR-01-03, FR-01-07 |
| **Truy vết — UC refs** | UC-01-01, UC-01-02, UC-01-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Hệ thống cần biết chính xác ai đang gọi. Có 2 loại danh tính: **người vận hành** (đăng nhập dashboard, dùng JWT) và **thiết bị Android** (gọi runtime API, dùng device key). Hai loại này không thể nhầm với nhau và không thể dùng đường còn lại của nhau. Ticket này build cả hai cùng lúc vì chúng chia sẻ infrastructure (issuer, verifier, lưu credential, audit hook) và đều là tiền điều kiện cho mọi route nghiệp vụ.

**Pain point hiện tại:** chưa có cơ chế cấp credential nào — mọi endpoint hoặc public hoặc không thể test. Khi DF-E-02 build device API và DF-E-03 build relay, cả hai cần ngay device-auth. Đồng thời dashboard cần JWT để gọi `/api/*`.

**Refresh token** quan trọng vì access token có thời hạn ngắn (15 phút) để giảm hậu quả khi token rò; refresh token (7-30 ngày) cho phép gia hạn mà không nhập lại mật khẩu. Refresh phải có **rotation** (issue cấp mới + revoke cũ) để chống replay.

**Device key** là chuỗi cấp khi pair thiết bị (DF-T-02-003), lưu băm trong DB. Mỗi request runtime kèm header `X-Device-Key`; server verify bằng cách so băm. Khác JWT ở chỗ device key không hết hạn theo thời gian (chỉ revoke chủ động) và không phải JWT — không có claims.

P0 vì chặn mọi Epic. Trong lộ trình đặc tả module 7, ticket này deliver "JWT user authentication" và "Device-auth qua device key" trạng thái Active.

## 3. Câu chuyện người dùng

> **Là** người vận hành
> **Tôi muốn** đăng nhập một lần và nhận access + refresh token, dùng access token gọi API, tự gia hạn qua refresh
> **Để** không phải nhập mật khẩu mỗi giờ và phiên làm việc liền mạch trong cả ngày

> **Là** thiết bị Android (qua agent)
> **Tôi muốn** gọi runtime API kèm device key
> **Để** gửi gesture/hierarchy/screenshot mà không cần JWT người dùng

Persona phụ: Admin tổ chức (gọi route admin-auth dùng cùng JWT).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp endpoint `POST /api/auth/login` nhận `{username, password}`, trả `{access_token, refresh_token, expires_in}` — trace FR-01-01.
- Hệ thống PHẢI cấp access token JWT có claims: `sub` (user_id), `org_id`, `roles[]`, `iat`, `exp`, `jti` — trace FR-01-03.
- Hệ thống PHẢI verify mật khẩu bằng bcrypt/argon2 (không SHA1, không plaintext) — trace FR-01-01.
- Hệ thống PHẢI cung cấp endpoint `POST /api/auth/refresh` nhận refresh token, trả access token mới + refresh token mới (rotation), revoke refresh cũ — trace FR-01-02.
- Hệ thống PHẢI lưu refresh token (hashed) trong DB với `expires_at`, `revoked_at`, `user_id`, `device_fingerprint`.
- Hệ thống PHẢI từ chối request user-auth không có header `Authorization: Bearer <token>` với 401 — trace FR-01-03.
- Hệ thống PHẢI từ chối access token hết hạn với 401 + body `{"code": "TOKEN_EXPIRED"}` — trace FR-01-03.
- Hệ thống PHẢI verify device key qua header `X-Device-Key`, so băm với DB, gắn `CurrentDevice` vào request context — trace FR-01-07.
- Hệ thống PHẢI tách biệt CurrentUser và CurrentDevice — JWT không cấp quyền device-auth và ngược lại — trace FR-01-07.
- Hệ thống PHẢI log mọi sự kiện auth (login OK, login FAIL, refresh, device-auth FAIL) vào audit log (tích hợp DF-T-01-005).
- Hệ thống PHẢI có endpoint `POST /api/auth/logout` revoke refresh token hiện tại.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Login thành công với credential đúng**

```
Given user "alice" trong organization "acme" tồn tại trong DB, mật khẩu đã được hash
When client gọi POST /api/auth/login với {"username":"alice","password":"<đúng>"}
Then response 200 với body {access_token, refresh_token, expires_in: 900}
And access_token decode được, có claims sub=alice.id, org_id=acme.id, exp ≈ now+15min
And refresh_token đã được lưu (hashed) trong bảng refresh_tokens
And audit log có entry "auth.login.success" với user_id và IP
```

**AC-2: Login fail với mật khẩu sai**

```
Given user "alice" tồn tại
When client gọi POST /api/auth/login với mật khẩu sai
Then response 401 với body {"code":"INVALID_CREDENTIALS"}
And response KHÔNG tiết lộ user có tồn tại hay không
And audit log có entry "auth.login.failed" với username và IP
And response time có thể không khác login đúng quá 50 ms (chống timing attack)
```

**AC-3: Refresh token rotation**

```
Given refresh_token R1 hợp lệ trong DB
When client gọi POST /api/auth/refresh với R1
Then response 200 với access_token mới và refresh_token mới R2
And R1 bị đánh dấu revoked_at trong DB
And lần thứ hai gọi refresh với R1 trả 401 + {"code":"REFRESH_REVOKED"}
And gọi với R2 vẫn hoạt động
```

**AC-4: Device-auth với device key đúng**

```
Given device "df-dev-001" đã pair, device_key="dk_xxx" lưu hash trong DB
When agent gọi POST /api/device/runtime/screenshot với header X-Device-Key: dk_xxx
Then request được nhận diện CurrentDevice = "df-dev-001"
And response 200 với binary screenshot
And không cần JWT người dùng
```

**AC-5: Device key sai bị từ chối**

```
Given không có device key nào tên "dk_wrong"
When agent gọi POST /api/device/runtime/screenshot với X-Device-Key: dk_wrong
Then response 401 với body {"code":"INVALID_DEVICE_KEY"}
And audit log có entry "device_auth.failed" với device_serial header (nếu có) và IP
```

**AC-6: JWT không dùng được trên device-auth route**

```
Given user JWT của alice còn hợp lệ
When alice cố gọi POST /api/device/runtime/screenshot với Authorization: Bearer <jwt>
Then response 401 với body {"code":"DEVICE_KEY_REQUIRED"}
And audit log entry "device_auth.failed_jwt_attempt"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm password policy chi tiết (min length, complexity, lockout) — DF-T-01-011.
- KHÔNG bao gồm RBAC enforcement (admin role check) — DF-T-01-003 (ticket này chỉ ghi `roles[]` vào claims).
- KHÔNG bao gồm UI login — DF-T-01-010.
- KHÔNG bao gồm SSO (SAML/OIDC) — out of scope module này, lộ trình.
- KHÔNG bao gồm MFA — lộ trình.
- KHÔNG bao gồm device key rotation định kỳ — DF-T-01-006 lo khung; rotation thực sự trên relay là DF-T-03-013.
- KHÔNG bao gồm tạo user account / pair device — DF-T-01-009 (user), DF-T-02-001 (device).
- KHÔNG bao gồm WebSocket auth flow — DF-T-01-012.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/auth/jwt_service.py` — issue, verify, decode.
- [ ] Module `device_farm/auth/password_service.py` — hash (argon2), verify.
- [ ] Module `device_farm/auth/refresh_token_service.py` — issue, rotate, revoke.
- [ ] Module `device_farm/auth/device_key_service.py` — verify hash.
- [ ] Middleware `JWTAuthMiddleware` gắn `CurrentUser` vào request.state.
- [ ] Middleware `DeviceKeyMiddleware` gắn `CurrentDevice` vào request.state.
- [ ] Dependency `get_current_user`, `get_current_device` cho FastAPI route.
- [ ] Endpoint `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout`.
- [ ] Đảm bảo timing-safe so sánh mật khẩu (constant time).

**Frontend** (`layer:frontend`)

- [ ] (Tích hợp đầy đủ ở DF-T-01-010; ở ticket này chỉ cần verify endpoint qua curl hoặc Postman collection.)

**Contract / API** (`layer:contract`)

- [ ] OpenAPI spec cho 3 endpoint auth + security scheme `bearerAuth` và `deviceKeyAuth`.
- [ ] Mã lỗi taxonomy: `INVALID_CREDENTIALS`, `TOKEN_EXPIRED`, `REFRESH_REVOKED`, `INVALID_DEVICE_KEY`, `DEVICE_KEY_REQUIRED`.

**Database / Migration** (`layer:db`)

- [ ] Bảng `users` (id, username, password_hash, org_id, created_at, status). Username UNIQUE per org.
- [ ] Bảng `refresh_tokens` (id, user_id, token_hash, expires_at, revoked_at, device_fingerprint, created_at). Index (user_id, revoked_at), (token_hash).
- [ ] Cột `device_key_hash` trên bảng `devices` (bảng full được tạo trong DF-T-02-001 — coordinate migration).
- [ ] Seed user dev `admin@dev` cho môi trường dev (KHÔNG seed cho production).

**Infra / DevOps** (`layer:infra`)

- [ ] Helm value `auth.jwt_secret_ref` đọc từ Kubernetes Secret.
- [ ] Helm value `auth.access_token_ttl_sec` (default 900), `auth.refresh_token_ttl_sec` (default 30 ngày).

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "Auth" — flow login, refresh, device-auth.
- [ ] `docs/runbooks/auth-incident.md` — quy trình revoke refresh token khi nghi rò rỉ.
- [ ] Mã lỗi catalog.

**Test** (`layer:test`)

- [ ] Unit test cho password hash/verify (test vector cố định).
- [ ] Unit test cho JWT issue/verify (kể cả expired, malformed, signature sai).
- [ ] Unit test cho refresh rotation.
- [ ] Integration test 6 AC.
- [ ] Test timing-attack: so login đúng vs login sai mật khẩu, chênh lệch < 50 ms p95.
- [ ] Security test: token nào hết hạn, token có claims sai signature, token jti đã revoke.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-002-01 | Positive | User alice tồn tại, mật khẩu hash đã lưu | POST /api/auth/login với credential đúng | 200, body có access_token + refresh_token, claims chính xác |
| TC-DF-T-01-002-02 | Positive | Refresh token R1 hợp lệ | POST /api/auth/refresh với R1 | 200, trả access_token mới và refresh_token R2; R1 bị revoke |
| TC-DF-T-01-002-03 | Positive | Device "df-001" pair, key đúng | GET /api/device/runtime/info với X-Device-Key đúng | 200, CurrentDevice nhận diện đúng device |
| TC-DF-T-01-002-04 | Negative | User alice tồn tại | POST /api/auth/login với mật khẩu sai | 401, code=INVALID_CREDENTIALS, audit log entry created, không lộ username tồn tại |
| TC-DF-T-01-002-05 | Negative | Token đã hết hạn (exp < now) | GET /api/me với token expired | 401, code=TOKEN_EXPIRED |
| TC-DF-T-01-002-06 | Negative | Refresh R1 đã được dùng (rotated thành R2) | POST /api/auth/refresh dùng lại R1 | 401, code=REFRESH_REVOKED, audit log entry "auth.refresh.replay_attempt" |
| TC-DF-T-01-002-07 | Negative | Có JWT alice hợp lệ | GET /api/device/runtime/info với Bearer JWT thay vì X-Device-Key | 401, code=DEVICE_KEY_REQUIRED |
| TC-DF-T-01-002-08 | Edge | JWT secret được rotate ở runtime | Token cấp trước rotation gọi API sau rotation | 401, code=TOKEN_EXPIRED hoặc INVALID_SIGNATURE; cơ chế grace overlap khi 2 secret song song có thể chấp nhận token cũ trong 5 phút |
| TC-DF-T-01-002-09 | Edge | 1000 lần login concurrent cùng user | Bắn 1000 POST login | Tất cả response 200 hoặc 429 (nếu rate-limit kích hoạt sau), không có refresh token nào trùng nhau, DB consistent |
| TC-DF-T-01-002-10 | Edge | Login sai mật khẩu nhiều lần | Chạy benchmark 100 lần login đúng và 100 lần sai mật khẩu | Chênh lệch trung bình thời gian phản hồi < 50 ms p95 (chống timing attack) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (cần runtime entrypoint), DF-T-01-004 (cần bảng `users` có `org_id`).

**Chặn:** DF-T-01-003 (RBAC đọc roles claim), DF-T-01-009 (user mgmt API), DF-T-01-010 (login UI), DF-T-01-011 (password policy), DF-T-01-012 (session lifecycle), DF-T-01-013 (rate-limit cần CurrentUser). Cross-Epic: DF-T-02-003 (device claim API cần CurrentUser), DF-T-03-013 (secure handshake cần device-auth).

**Phụ thuộc giữa Epic:** Cấp pre-requisite cho mọi route nghiệp vụ DF-E-02-11.

**Rủi ro:**

- **R1 — JWT secret rò rỉ.** Tác động: mọi token đang hoạt động có thể bị forge. Giảm thiểu: rotation framework (DF-T-01-006) + jti revocation list trong DB cho phép revoke token theo jti.
- **R2 — Replay attack với refresh token.** Giảm thiểu: rotation bắt buộc + log replay → flag user.
- **R3 — Timing attack lộ user tồn tại.** Giảm thiểu: constant-time compare + dummy hash check khi user không tồn tại.
- **R4 — Device key bị log trong traceback.** Giảm thiểu: header `X-Device-Key` phải trong list redact của logger; CI grep check.

**Phụ thuộc bên ngoài:** `python-jose` hoặc `pyjwt`, `argon2-cffi`, OpenSSL ≥ 3.0.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85% cho `device_farm/auth/*`.
- [ ] 10 test case đã có automation hoặc evidence manual.
- [ ] Security review từ Platform Engineer lead (checklist OWASP ASVS L2 cho auth).
- [ ] `docs/modules/platform-runtime.md` + `docs/runbooks/auth-incident.md` cập nhật.
- [ ] OpenAPI spec có security scheme `bearerAuth` và `deviceKeyAuth`.
- [ ] Telemetry: metric `auth.login.duration_ms`, `auth.login.failed_count`, `auth.refresh.replay_count`.
- [ ] Audit log emit cho 4 sự kiện (login OK, login FAIL, refresh, device-auth FAIL).
- [ ] Logger redact list bao gồm `password`, `Authorization`, `X-Device-Key`, `refresh_token`. Test grep CI confirm.
- [ ] Performance: p99 login < 1 s, p99 verify JWT < 5 ms.
- [ ] Đã chạy security scan (bandit + dependency vuln check) clean.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — FR-01-01, FR-01-02, FR-01-03, FR-01-07.
- **Ma trận năng lực:** "JWT user authentication", "Device-auth qua device key".
- **Nhóm người dùng:** Platform Engineer; tất cả persona vận hành tiêu thụ JWT qua login.
- **Thuật ngữ:** JWT, Refresh token, Device-auth, Device key.
- **Lộ trình:** M1 Infrastructure Bootstrap.
- **Risk control:** OWASP ASVS L2 mục V2 Authentication, V3 Session.
