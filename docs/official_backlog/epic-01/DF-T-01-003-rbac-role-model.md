# DF-T-01-003 — RBAC role model & enforcement

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-003 |
| **Title** | RBAC role model & enforcement (org admin / member) |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:contract`, `layer:db`, `type:feature`, `risk:auth`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-04, FR-01-13 |
| **Truy vết — UC refs** | UC-01-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Sau khi danh tính đã được xác minh (DF-T-01-002), hệ thống cần biết người gọi **được phép làm gì**. Đặc tả module định nghĩa hai cấp: route admin-auth (chỉ admin tổ chức được gọi) và route user-auth (mọi thành viên đều gọi được nếu thuộc tổ chức tương ứng). Ngoài ra, một quy ước quan trọng (FR-01-13): module runtime chỉ verify role ở cấp boundary; **kiểm tra ownership chi tiết "user này có sở hữu campaign này không" là trách nhiệm của route nghiệp vụ**, không phải runtime.

Ticket này build cả hai khả năng: (1) decorator/dependency để route khai báo role requirement (`@requires_role("admin")`), runtime tự reject 403 nếu CurrentUser không có role đó; (2) framework helper `assert_ownership(resource, current_user)` mà route nghiệp vụ dùng để kiểm tra ownership theo cùng convention. Framework này sẽ dùng xuyên suốt DF-E-02-11.

Open question của đặc tả module ("Cần thêm vai trò chi tiết — chỉ xem campaign, chỉ chạy scenario có sẵn?") tạm thời chốt: **giữ 2 role admin/member ở M1**, nhưng model design phải để mở dễ thêm role granular sau. Vì vậy schema dùng bảng `roles` thay vì enum cứng.

P0 vì block các route admin (vd quản lý thành viên DF-T-01-009, force-release session DF-T-02-013, fleet stats DF-T-02-013).

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức
> **Tôi muốn** chỉ tôi (và admin khác) gọi được các route quản trị, thành viên thường bị từ chối
> **Để** kiểm soát ai đổi cấu hình tổ chức và mời thành viên mới

> **Là** Platform Engineer
> **Tôi muốn** có decorator `@requires_role` và helper `assert_ownership` thống nhất
> **Để** mọi route nghiệp vụ trong Epic sau dùng cùng pattern, không reinvent

## 4. Yêu cầu chức năng

- Hệ thống PHẢI hỗ trợ role gắn vào user trong phạm vi organization: tối thiểu `admin` và `member` — trace FR-01-04.
- Hệ thống PHẢI decorator `@requires_role("admin")` reject CurrentUser không có role với 403 + body `{"code":"FORBIDDEN_ROLE"}` — trace FR-01-04.
- Hệ thống PHẢI verify role chỉ trong phạm vi tổ chức của resource đang gọi; admin của org A không có quyền admin trên route gắn vào org B — trace FR-01-04, FR-01-05.
- Hệ thống PHẢI cung cấp helper `assert_ownership(resource, user)` raise 403/404 nếu resource không thuộc org của user — trace FR-01-13.
- Hệ thống PHẢI có endpoint `GET /api/me` trả CurrentUser kèm `roles[]` và `org_id` — đã có claims trong JWT nhưng client cần endpoint canonical.
- Hệ thống PHẢI ghi audit log khi role được gán/thu hồi — tích hợp DF-T-01-005.
- Hệ thống PHẢI cấu trúc bảng `roles`, `user_roles` cho phép thêm role mới sau mà không migration phức tạp.
- Hệ thống NÊN có CI check: route trong `admin_router` phải có `@requires_role("admin")` hoặc decorator equivalent.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Admin gọi route admin thành công**

```
Given user "bob" có role "admin" trong org "acme"
And route GET /api/admin/members yêu cầu @requires_role("admin")
When bob gọi GET /api/admin/members với JWT hợp lệ
Then response 200 với danh sách members của acme
And audit log entry "admin.access" với route name và user_id
```

**AC-2: Member thường bị từ chối route admin**

```
Given user "carol" có role "member" trong org "acme" (không phải admin)
When carol gọi GET /api/admin/members với JWT hợp lệ
Then response 403 với body {"code":"FORBIDDEN_ROLE", "required":"admin"}
And audit log entry "admin.access.denied" với user_id và route
```

**AC-3: Cross-tenant admin không có quyền admin trên org khác**

```
Given user "dave" là admin trong org "beta"
And resource "campaign-123" thuộc org "acme"
When dave cố gọi GET /api/admin/campaigns/campaign-123 (nếu route đó có)
Then response 403 hoặc 404 (không lộ tồn tại)
And dave KHÔNG thấy được dữ liệu của acme
```

**AC-4: Ownership helper bắt cross-org**

```
Given route nghiệp vụ user-auth "GET /api/campaigns/{id}" gọi assert_ownership
And campaign "x" thuộc org "acme"
And user "dave" thuộc org "beta"
When dave gọi GET /api/campaigns/x
Then helper raise OwnershipError
And response 404 với body {"code":"NOT_FOUND"} (không 403 để tránh leak)
And audit log entry "ownership.violation" với resource_id và user_id
```

**AC-5: GET /api/me trả role canonical**

```
Given user bob đã login, JWT hợp lệ
When bob gọi GET /api/me
Then response 200 với {user_id, username, org_id, org_name, roles:["admin"]}
And response không bao gồm password_hash, jti, hoặc field nhạy cảm
```

**AC-6: Role thay đổi runtime có hiệu lực ở lần verify kế tiếp**

```
Given bob có role "admin"; access token T1 đã cấp với roles=["admin"] (TTL 15 phút)
When admin khác revoke role admin của bob
And bob gọi route admin trong vòng TTL của T1
Then có 2 cách chấp nhận: (a) reject vì DB roles không còn (re-check DB mỗi request), HOẶC (b) chấp nhận token còn hạn nhưng forward role từ JWT — phải chọn ONE và document rõ
And document trong runbook auth-incident rằng để revoke ngay phải gọi /api/auth/sessions/revoke (DF-T-01-012)
```

> **Decision:** ticket này chọn (a) — re-check DB mỗi request user-auth admin route. Trade-off: 1 query DB extra mỗi request, nhưng đảm bảo revoke role có hiệu lực ngay. Caching 60s acceptable.

## 6. Ngoài phạm vi

- KHÔNG bao gồm role granular ("chỉ xem campaign", "chỉ chạy scenario") — open question, đưa vào lộ trình sau.
- KHÔNG bao gồm UI gán role — DF-T-01-009 và DF-E-11.
- KHÔNG bao gồm RBAC cho device (device có identity riêng, không qua role).
- KHÔNG bao gồm policy engine (OPA/Casbin) — quá phức tạp cho 2 role, defer.
- KHÔNG bao gồm audit log table (chỉ emit event) — DF-T-01-005 lo storage.
- KHÔNG bao gồm route admin cụ thể — chỉ build framework, route admin thực được tạo ở DF-T-01-009 và Epic sau.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/auth/rbac.py` — `requires_role`, `requires_any_role`, `assert_ownership`.
- [ ] Service `RoleService` query DB cho role check (có cache 60s per user_id).
- [ ] Tích hợp decorator vào FastAPI dependency.
- [ ] Endpoint `GET /api/me`.
- [ ] Audit hook gọi từ decorator khi 403.

**Frontend** (`layer:frontend`)

- [ ] (Defer DF-T-01-010, chỉ cần đảm bảo /api/me return shape ổn định.)

**Contract / API** (`layer:contract`)

- [ ] OpenAPI spec cho /api/me và mã lỗi FORBIDDEN_ROLE, NOT_FOUND.
- [ ] Document quy ước "ownership check trả 404 thay vì 403 cho cross-org".

**Database / Migration** (`layer:db`)

- [ ] Bảng `roles` (id, name, description). Seed: `admin`, `member`.
- [ ] Bảng `user_roles` (user_id, role_id, org_id, granted_at, granted_by). Composite PK (user_id, role_id, org_id).
- [ ] Index (user_id, org_id) trên user_roles.
- [ ] Migration backfill: với user hiện hữu, gán role "member" mặc định; với seed admin@dev, gán "admin".

**Infra / DevOps** (`layer:infra`)

- [ ] CI check: route trong `admin_router` phải có `@requires_role("admin")` (lint script).

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "RBAC" — decorator usage, ownership pattern.
- [ ] ADR-001: "Tại sao chọn 2 role thay vì policy engine".
- [ ] Quy ước "ownership trả 404 thay vì 403" trong contract doc.

**Test** (`layer:test`)

- [ ] Unit test cho RoleService (cache hit/miss).
- [ ] Integration test 6 AC.
- [ ] Test fuzz: route admin thử gọi với JWT của 100 user member khác nhau, tất cả phải 403.
- [ ] Test cross-org: admin org A thử truy cập 50 resource org B random, tất cả phải 403/404, không leak data.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-003-01 | Positive | bob có role admin org acme | GET /api/admin/members với JWT bob | 200, danh sách members acme |
| TC-DF-T-01-003-02 | Positive | carol có role member, gọi /api/me | GET /api/me | 200, roles=["member"], org_id=acme |
| TC-DF-T-01-003-03 | Positive | dave là admin org beta, helper assert_ownership được gọi | dave gọi route user-auth cho campaign thuộc beta | helper pass, 200 |
| TC-DF-T-01-003-04 | Negative | carol (member acme) gọi route admin | GET /api/admin/members | 403, code=FORBIDDEN_ROLE, audit log entry |
| TC-DF-T-01-003-05 | Negative | dave (admin beta) gọi route admin của acme | GET /api/admin/orgs/acme/members | 403 hoặc 404; dữ liệu acme KHÔNG lộ |
| TC-DF-T-01-003-06 | Negative | dave gọi route nghiệp vụ truy cập campaign org acme | GET /api/campaigns/{acme_campaign_id} | 404 (không 403), code=NOT_FOUND |
| TC-DF-T-01-003-07 | Edge | bob có role admin; admin khác revoke role | Revoke role lúc T0; bob gọi admin route tại T0+5s với JWT cũ | 403 (cache RoleService hết hiệu lực sau 60s, nhưng vì re-check mỗi request admin route, phản ứng ngay) |
| TC-DF-T-01-003-08 | Edge | User có 0 role (vừa bị revoke hết) | Gọi route user-auth bình thường (chỉ requires authenticated) | 200 nếu route không requires_role; 403 nếu requires_role |
| TC-DF-T-01-003-09 | Edge | Org acme bị disable (status=disabled); bob vẫn còn JWT | bob gọi /api/me | 403 với code=ORG_DISABLED (hoặc 401 + token invalidation tùy implementation; phải document) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-002 (cần CurrentUser), DF-T-01-004 (cần org_id trong context).

**Chặn:** DF-T-01-005 (audit emit từ rbac decorator), DF-T-01-009 (mọi route admin), DF-T-02-011 (manual override fleet), DF-T-02-013 (fleet stats admin-only).

**Phụ thuộc giữa Epic:** Framework `assert_ownership` được mọi route nghiệp vụ DF-E-02-11 dùng.

**Rủi ro:**

- **R1 — Ownership check bị bỏ sót trong route nghiệp vụ.** Tác động: cross-tenant leak. Giảm thiểu: code review checklist + integration test bắt buộc cho mỗi route nghiệp vụ + grep CI tìm route không gọi `assert_ownership`.
- **R2 — Cache role gây stale.** Giảm thiểu: TTL 60s + force refresh khi role change.
- **R3 — RBAC framework không scale khi thêm role chi tiết sau.** Giảm thiểu: schema `roles`/`user_roles` flexible; design doc cho extension.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85% cho `device_farm/auth/rbac.py`.
- [ ] 9 test case automation.
- [ ] ADR-001 merged trong `docs/adr/`.
- [ ] `docs/modules/platform-runtime.md` cập nhật.
- [ ] CI lint check `admin_router` đã active 3 PR liên tiếp pass.
- [ ] Telemetry: counter `rbac.denied.count` group by route và role.
- [ ] Audit log entry cho admin.access, admin.access.denied, ownership.violation.
- [ ] Security review từ Platform Engineer lead.
- [ ] Performance: p99 verify role check < 10 ms (với cache).

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — FR-01-04, FR-01-13.
- **Ma trận năng lực:** "Multi-tenancy theo organization".
- **Nhóm người dùng:** Admin tổ chức, Platform Engineer.
- **Thuật ngữ:** Organization.
- **ADR liên quan:** ADR-001 (sẽ tạo trong ticket này) — "RBAC giữ 2 role + ownership helper thay vì policy engine".
