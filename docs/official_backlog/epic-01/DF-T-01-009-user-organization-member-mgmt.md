# DF-T-01-009 — User & organization member management API

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-009 |
| **Title** | API quản lý user và thành viên tổ chức (invite, disable, role change) |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:contract`, `layer:db`, `type:feature`, `risk:auth`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-04, FR-01-05, FR-01-06 |
| **Truy vết — UC refs** | UC-01-03, UC-01-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Sau khi đã có model org và user (DF-T-01-004), JWT auth (DF-T-01-002), RBAC (DF-T-01-003), Admin tổ chức cần workflow cụ thể để **quản lý thành viên trong org của mình**: mời thành viên mới qua email, chấp nhận lời mời (tạo account), vô hiệu hóa thành viên rời tổ chức, đổi role giữa admin và member. Đây là FR-01-06 trong đặc tả module với mức Must.

Ticket build CRUD đầy đủ:
- `POST /api/admin/members/invite` — admin gửi lời mời (email + role mong muốn). Tạo `pending_invitation` với token có TTL 7 ngày.
- `POST /api/auth/accept-invite` — user dùng token mở account mới (đặt password), gắn vào org đúng.
- `GET /api/admin/members` — list members trong org.
- `PATCH /api/admin/members/{user_id}` — đổi role (admin ↔ member).
- `POST /api/admin/members/{user_id}/disable` — vô hiệu hóa (status=disabled), user không login được.
- `POST /api/admin/members/{user_id}/enable` — kích hoạt lại.

P0 vì onboarding khách hàng B2B đầu tiên cần luồng này. Pain point Admin tổ chức hiện tại: không có cách thêm thành viên vào team mà không nhờ Platform Engineer can thiệp DB.

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức acme
> **Tôi muốn** mời thành viên mới qua email, đổi role, hoặc vô hiệu hóa người đã rời team
> **Để** quản lý quyền truy cập trong org acme mà không phải nhờ Platform Engineer

> **Là** thành viên mới được mời
> **Tôi muốn** click link mời và đặt mật khẩu của riêng tôi
> **Để** không cần admin tạo và chia sẻ mật khẩu

## 4. Yêu cầu chức năng

- Hệ thống PHẢI `POST /api/admin/members/invite` body `{email, role}` (admin tổ chức) — trace FR-01-06.
- Hệ thống PHẢI tạo `invitation` token (UUID), TTL 7 ngày, lưu DB.
- Hệ thống PHẢI gửi email (qua provider) chứa link `/accept-invite?token=...`.
- Hệ thống PHẢI `POST /api/auth/accept-invite` body `{token, username, password}` — public.
- Hệ thống PHẢI verify token, tạo user trong DB với org_id và role từ invitation; mark invitation status=accepted.
- Hệ thống PHẢI từ chối token đã expire, đã dùng, hoặc không tồn tại với 400.
- Hệ thống PHẢI `GET /api/admin/members` trả paginated list với fields `{user_id, username, email, roles, status, last_login_at, created_at}` — admin only, scoped to org.
- Hệ thống PHẢI `PATCH /api/admin/members/{user_id}` body `{roles: [...]}` thay đổi role — trace FR-01-04, FR-01-06.
- Hệ thống PHẢI `POST /api/admin/members/{user_id}/disable` set `status=disabled`; revoke refresh token của user; lần auth kế tiếp 403.
- Hệ thống PHẢI emit audit log cho mọi action: `member.invited`, `member.invitation_accepted`, `member.role_changed`, `member.disabled`, `member.enabled` — trace DF-T-01-005.
- Hệ thống PHẢI không cho admin tự disable mình (tránh lock-out org); ít nhất 1 admin phải tồn tại tại mọi thời điểm — trace FR-01-04.
- Hệ thống PHẢI rate-limit invite endpoint (10/h per admin) để chống abuse.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Admin invite, member accept**

```
Given bob admin org acme
When bob POST /api/admin/members/invite với {email: "new@example.com", role: "member"}
Then response 201 với invitation_id
And email gửi đến new@example.com chứa link /accept-invite?token=<uuid>
And audit log entry "member.invited"
When new user click link và POST /api/auth/accept-invite với {token, username:"newbie", password:"Strong#123"}
Then response 200 với access_token (auto-login)
And user "newbie" tạo trong DB, org_id=acme, role="member", status="active"
And invitation status=accepted
And audit log entry "member.invitation_accepted"
```

**AC-2: Token expire bị từ chối**

```
Given invitation token T tạo 8 ngày trước (TTL 7 ngày)
When user POST /api/auth/accept-invite với T
Then response 400 với code INVITATION_EXPIRED
And không tạo user
```

**AC-3: Token đã dùng không thể replay**

```
Given invitation T đã được accept thành công
When ai đó POST /api/auth/accept-invite lần thứ hai với T
Then response 400 với code INVITATION_ALREADY_USED
And không tạo user mới
```

**AC-4: Admin disable member**

```
Given bob admin acme, carol member acme, carol đang có 2 refresh token active
When bob POST /api/admin/members/{carol.id}/disable
Then response 200
And carol.status = "disabled"
And 2 refresh token của carol bị revoke
And carol gọi /api/me với access token còn TTL → 403 (do re-check status mỗi request) hoặc đến khi token expire → 401 (decision: re-check status mỗi request user-auth)
And audit log entry "member.disabled"
```

**AC-5: Đổi role**

```
Given carol member; bob admin
When bob PATCH /api/admin/members/{carol.id} với {roles:["admin"]}
Then response 200
And carol bây giờ là admin
And audit log "member.role_changed" với old_roles, new_roles, actor=bob
And carol có thể gọi route admin sau khi JWT mới (hoặc trong vòng cache 60s nếu DF-T-01-003 cache)
```

**AC-6: Không thể disable admin cuối cùng**

```
Given acme chỉ còn 1 admin là bob
When bob cố POST /api/admin/members/{bob.id}/disable
Then response 400 với code CANNOT_DISABLE_LAST_ADMIN
And bob vẫn active
```

**AC-7: Cross-tenant không invite được**

```
Given bob admin acme
When bob cố POST /api/admin/members/invite với body chứa target_org="beta" (nếu cố hack)
Then org_id bị ignore từ body (theo DF-T-01-004)
And invitation tạo cho acme, không phải beta
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI invite (form, email template visual) — DF-E-11.
- KHÔNG bao gồm SSO provisioning (SCIM) — đưa vào lộ trình sau.
- KHÔNG bao gồm role granular ngoài admin/member — DF-T-01-003 đã quyết keep simple.
- KHÔNG bao gồm transfer ownership org — defer.
- KHÔNG bao gồm bulk invite — defer.
- KHÔNG bao gồm email provider integration setup (SES, SendGrid) — DevOps task; ở ticket này chỉ assume có abstraction `email_service.send(...)`.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/members/service.py` — invite, accept, list, update_role, disable, enable.
- [ ] Module `device_farm/members/invitation_token.py` — generate, verify, mark used.
- [ ] Endpoints với decorator `@requires_role("admin")` áp dụng đúng.
- [ ] Tích hợp `emit_audit_event` cho từng action.
- [ ] Helper kiểm tra "last admin guard".
- [ ] Rate-limit invite (DF-T-01-013 ticket riêng nhưng ticket này phải có placeholder).

**Frontend** (`layer:frontend`)

- [ ] (DF-E-11.)

**Contract / API** (`layer:contract`)

- [ ] OpenAPI spec cho 6 endpoint.
- [ ] Mã lỗi: INVITATION_EXPIRED, INVITATION_ALREADY_USED, EMAIL_ALREADY_REGISTERED, CANNOT_DISABLE_LAST_ADMIN.
- [ ] Email template content (text + HTML) commit trong repo.

**Database / Migration** (`layer:db`)

- [ ] Bảng `invitations` (id, org_id, email, role, token_hash, expires_at, accepted_at, accepted_by_user_id, created_by, created_at).
- [ ] Index (token_hash), (org_id, expires_at).
- [ ] Cột `status` (active/disabled/pending) trên bảng `users` (đã có status từ DF-T-01-002, chỉ cần ensure).

**Infra / DevOps** (`layer:infra`)

- [ ] Helm value `email.provider`, `email.from_address`.
- [ ] Helm value `invitation.ttl_days` (default 7).

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "Member management".
- [ ] Email template flow doc.

**Test** (`layer:test`)

- [ ] Unit test invitation_token (generate, verify, expire, replay).
- [ ] Integration test 7 AC.
- [ ] Test concurrent: 2 admin cùng đổi role 1 user → DB consistent, một thành công.
- [ ] Test cross-tenant: admin acme thử mời với org_id=beta → forced to acme.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-009-01 | Positive | bob admin acme | POST /api/admin/members/invite {email, role:"member"} | 201, invitation tạo, email send queued |
| TC-DF-T-01-009-02 | Positive | Token hợp lệ | POST /api/auth/accept-invite | 200, user tạo, auto-login |
| TC-DF-T-01-009-03 | Positive | bob admin, carol member | PATCH /api/admin/members/{carol.id} {roles:["admin"]} | 200, carol role admin, audit entry |
| TC-DF-T-01-009-04 | Positive | bob admin, carol active | POST /api/admin/members/{carol.id}/disable | 200, carol.status=disabled, refresh token revoked |
| TC-DF-T-01-009-05 | Negative | Token 8 ngày tuổi (TTL 7) | POST /api/auth/accept-invite | 400 INVITATION_EXPIRED |
| TC-DF-T-01-009-06 | Negative | Token đã dùng | Replay accept-invite | 400 INVITATION_ALREADY_USED |
| TC-DF-T-01-009-07 | Negative | Email đã đăng ký trong org khác | POST invite cho email đó | 400 EMAIL_ALREADY_REGISTERED hoặc tạo invitation pending — quyết định: vẫn được mời (mỗi email có thể thuộc nhiều org nếu cùng người), nhưng nếu cùng org và user đã tồn tại → 400 |
| TC-DF-T-01-009-08 | Negative | acme có 1 admin bob, bob tự disable | POST /api/admin/members/{bob.id}/disable | 400 CANNOT_DISABLE_LAST_ADMIN |
| TC-DF-T-01-009-09 | Negative | carol member acme cố gọi /api/admin/members | GET /api/admin/members | 403 FORBIDDEN_ROLE |
| TC-DF-T-01-009-10 | Edge | bob invite 11 user trong 1 giờ | POST invite lần thứ 11 | 429 TOO_MANY_REQUESTS (rate-limit) |
| TC-DF-T-01-009-11 | Edge | 2 admin cùng đổi role carol cùng lúc | 2 PATCH concurrent | DB consistent, 1 success 1 conflict (409); audit log entries đúng số lượng |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-002 (JWT, login), DF-T-01-003 (RBAC), DF-T-01-004 (tenant), DF-T-01-005 (audit).

**Chặn:** DF-E-11 UI member management.

**Phụ thuộc giữa Epic:** Email provider abstraction sẽ được Notif & Analytics (DF-E-09) re-use.

**Rủi ro:**

- **R1 — Email không gửi được (provider down).** Giảm thiểu: queue retry; admin có thể resend invite qua API.
- **R2 — Invitation token bị brute force.** Giảm thiểu: token UUIDv4 (128-bit entropy) + rate-limit + audit log mọi attempt.
- **R3 — Race condition khi disable admin cuối.** Giảm thiểu: transaction lock + check count.

**Phụ thuộc bên ngoài:** Email service provider (SES/SendGrid/Mailgun).

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85%.
- [ ] 11 test case automation.
- [ ] OpenAPI spec đầy đủ 6 endpoint.
- [ ] Email template reviewed bởi team copywriting (nếu có) hoặc Platform Engineer.
- [ ] Audit log emit cho 5 sự kiện.
- [ ] Security review từ Platform Engineer.
- [ ] Đã chạy thử flow end-to-end với email staging provider.
- [ ] Telemetry: `member.invite.count`, `member.invite.accept_rate`, `member.disable.count`.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — FR-01-04, FR-01-05, FR-01-06.
- **Ma trận năng lực:** "Multi-tenancy theo organization".
- **Nhóm người dùng:** Admin tổ chức.
- **Thuật ngữ:** Organization.
