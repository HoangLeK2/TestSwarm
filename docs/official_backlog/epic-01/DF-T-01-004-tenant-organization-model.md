# DF-T-01-004 — Tenant (organization) model & data scoping

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-004 |
| **Title** | Mô hình tổ chức (organization) và scoping dữ liệu multi-tenancy |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `risk:data-loss`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-05, FR-01-13 |
| **Truy vết — UC refs** | UC-01-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Device Farm là SaaS B2B phục vụ nhiều tổ chức khách hàng song song trên cùng một deployment. Yêu cầu cứng: **dữ liệu của org A không bao giờ được nhìn thấy từ org B**, không qua API, không qua list endpoint, không qua search, không qua filter trống. Một bug ở đây sẽ làm hỏng hợp đồng B2B và có thể vi phạm pháp lý.

Ticket này build mô hình tenant ở 3 tầng: (1) **schema** — bảng `organizations` và cột `org_id` bắt buộc trên mọi bảng nghiệp vụ; (2) **enforcement** — ORM-level default filter tự động thêm `WHERE org_id = :current_org` cho mọi query; (3) **convention** — quy ước route không bao giờ trust `org_id` từ request body/param, chỉ trust từ `CurrentUser.org_id`.

Quyết định thiết kế: **một deployment dùng shared schema** (tất cả org dùng chung bảng, phân biệt qua `org_id`), không phải schema-per-tenant. Lý do: dễ migration, dễ analytic, đủ cho quy mô target (50-200 tổ chức). Trade-off: enforcement filter là điểm tử huyệt — bug ở đây bị tránh bằng test bắt buộc.

P0 cứng. Mọi bảng nghiệp vụ trong DF-E-02-11 đều phải có `org_id` ngay từ migration đầu tiên — không thể bolt-on sau.

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức acme
> **Tôi muốn** tôi và team chỉ thấy được tài nguyên thuộc org acme (device, campaign, content, account)
> **Để** dữ liệu của org khác không bao giờ rò sang acme và ngược lại

> **Là** Platform Engineer
> **Tôi muốn** có ORM mixin/base class tự inject `org_id` filter
> **Để** team nghiệp vụ không cần nhớ thêm `.filter(org_id=...)` mỗi query

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có bảng `organizations` (id, name, slug, status, created_at, plan) — trace FR-01-05.
- Hệ thống PHẢI bảng `users` có cột `org_id` NOT NULL FK → organizations — trace FR-01-05.
- Hệ thống PHẢI cung cấp ORM base class `TenantScopedModel` với cột `org_id` bắt buộc — trace FR-01-05.
- Hệ thống PHẢI có session-level default filter tự thêm `WHERE org_id = :current_org` khi `CurrentUser` đã gắn — trace FR-01-05.
- Hệ thống PHẢI reject request mà route nghiệp vụ cố override `org_id` trong body — trace FR-01-13.
- Hệ thống PHẢI cung cấp helper `enforce_tenant(record, current_user)` raise nếu `record.org_id != current_user.org_id`.
- Hệ thống PHẢI có endpoint `GET /api/me/organization` trả thông tin org hiện tại của user.
- Hệ thống PHẢI có CI integration test "cross-tenant smoke" — tạo 2 org, mỗi org 1 resource sample, gọi list endpoint với user org A và xác nhận không thấy resource org B.
- Hệ thống PHẢI hỗ trợ `org.status = "disabled"` — user thuộc org disabled không thể login (xác thực 403 với code ORG_DISABLED).
- Hệ thống NÊN có `org.plan` (free/standard/enterprise) để các module sau gắn quota.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: User chỉ thấy resource thuộc org của mình**

```
Given org "acme" có 5 device, org "beta" có 3 device
And alice là member của acme
When alice gọi GET /api/devices
Then response trả về đúng 5 device của acme
And 3 device của beta không xuất hiện
And response không có field nào lộ tồn tại của beta
```

**AC-2: User không truy cập resource org khác bằng ID**

```
Given device "dev-beta-001" thuộc org beta
And alice là member của acme
When alice gọi GET /api/devices/dev-beta-001
Then response 404 với body {"code":"NOT_FOUND"}
And response time không khác với ID không tồn tại (chống enumeration)
And audit log entry "tenant.cross_access_attempt" với user_id, resource_id, attempted_org_id
```

**AC-3: Route không trust org_id từ body**

```
Given alice (member acme) POST /api/devices/pair với body {"org_id":"beta", "serial":"..."}
When request được xử lý
Then org_id trong body bị ignore
And device được tạo với org_id = acme (từ CurrentUser)
And response có warning header X-Warning: "body.org_id ignored"
```

**AC-4: Org disabled không cho login**

```
Given org "stale" có status="disabled"
And user "ed" thuộc org stale
When ed gọi POST /api/auth/login với credential đúng
Then response 403 với body {"code":"ORG_DISABLED"}
And không cấp access_token
And audit log "auth.login.org_disabled"
```

**AC-5: CI cross-tenant smoke pass**

```
Given CI pipeline có job "cross-tenant-smoke"
When job chạy: tạo 2 org, mỗi org 1 user và 1 device, gọi list/get/update từ user A
Then tất cả assertion về data isolation pass
And nếu fail, PR bị block không merge
```

**AC-6: ORM default filter active**

```
Given TenantScopedModel "Campaign"; alice attached CurrentUser context
When code gọi session.query(Campaign).all() KHÔNG kèm filter
Then SQL emit có WHERE clause "campaigns.org_id = '<acme_id>'"
And test SQL assertion confirm
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI tạo organization (signup flow) — defer DF-E-11 hoặc admin internal.
- KHÔNG bao gồm billing/quota enforcement — `org.plan` chỉ là metadata; enforcement riêng.
- KHÔNG bao gồm schema-per-tenant — explicit out (ADR-002).
- KHÔNG bao gồm cross-org sharing (vd "share campaign với partner org") — đưa vào lộ trình sau.
- KHÔNG bao gồm migration đổi user từ org này sang org khác — process thủ công admin internal.
- KHÔNG bao gồm bảng nghiệp vụ (devices, campaigns, etc.) — chỉ build `organizations` và `users` ở ticket này; các bảng khác build ở Epic tương ứng nhưng phải kế thừa `TenantScopedModel`.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/tenancy/models.py` — Organization, TenantScopedModel base.
- [ ] Module `device_farm/tenancy/context.py` — TenantContext (contextvar lưu current_org_id mỗi request).
- [ ] Middleware `TenantContextMiddleware` set context từ CurrentUser.
- [ ] SQLAlchemy event listener `before_compile` inject filter.
- [ ] Helper `enforce_tenant(record, user)`.
- [ ] Endpoint `GET /api/me/organization`.
- [ ] Reject `org_id` field từ request body (Pydantic exclude với warning).

**Frontend** (`layer:frontend`)

- [ ] (Phụ thuộc shape /api/me/organization để hiển thị org name trên dashboard header — implement chi tiết DF-E-11.)

**Contract / API** (`layer:contract`)

- [ ] OpenAPI spec cho /api/me/organization.
- [ ] Document quy ước "org_id never accepted from client".

**Database / Migration** (`layer:db`)

- [ ] Bảng `organizations` (id UUID, name, slug UNIQUE, status, plan, created_at, updated_at).
- [ ] Cập nhật bảng `users` từ DF-T-01-002 thêm org_id NOT NULL FK.
- [ ] Index (org_id, created_at) làm template cho các bảng kế thừa.
- [ ] Seed org "dev-org" cho môi trường dev.
- [ ] Migration helper SQL function `current_org_id()` đọc từ session variable (cho query thuần SQL nếu cần).

**Infra / DevOps** (`layer:infra`)

- [ ] CI job `cross-tenant-smoke` — chạy script kiểm tra isolation.
- [ ] Helm value `tenancy.strict_mode` (default true) — chế độ strict yêu cầu mọi query phải có org filter explicit hoặc qua TenantScopedModel.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "Tenancy".
- [ ] ADR-002: "Shared schema vs schema-per-tenant — chọn shared".
- [ ] Quy ước cho route nghiệp vụ: `assert_ownership` cộng `enforce_tenant`.

**Test** (`layer:test`)

- [ ] Unit test cho TenantContextMiddleware (gắn/clear context đúng).
- [ ] Unit test cho SQLAlchemy event listener (SQL emit có WHERE).
- [ ] Integration test cross-tenant smoke (6 AC).
- [ ] Fuzz test: 20 endpoint user-auth, mỗi endpoint thử 50 random org-A user gọi org-B resource → tất cả phải 404.
- [ ] Test ORG_DISABLED block login.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-004-01 | Positive | 2 org acme/beta, mỗi org 5 device | alice (acme) GET /api/devices | 200, danh sách đúng 5 device của acme |
| TC-DF-T-01-004-02 | Positive | alice đã login | GET /api/me/organization | 200, body {id: acme.id, name:"Acme", plan:"standard"} |
| TC-DF-T-01-004-03 | Positive | TenantScopedModel Campaign | Code session.query(Campaign).all() trong context | SQL có WHERE campaigns.org_id = '<acme_id>' |
| TC-DF-T-01-004-04 | Negative | dev-beta-001 thuộc beta | alice GET /api/devices/dev-beta-001 | 404 NOT_FOUND, audit entry tenant.cross_access_attempt |
| TC-DF-T-01-004-05 | Negative | org "stale" disabled | ed login | 403 ORG_DISABLED |
| TC-DF-T-01-004-06 | Negative | alice POST với body {"org_id":"beta",...} | Request đến route nghiệp vụ | body.org_id bị ignore, record tạo với org_id=acme, header X-Warning có |
| TC-DF-T-01-004-07 | Edge | Resource id không tồn tại ở bất kỳ org nào | alice GET /api/devices/nonexistent | 404 NOT_FOUND, response time tương đương TC-04 (chống enumeration) |
| TC-DF-T-01-004-08 | Edge | TenantContext không được set (background job, hệ thống nội bộ) | Code session.query(Campaign).all() outside request | Behavior phụ thuộc strict_mode: strict=true → raise; strict=false → query không lọc (cần explicit override) |
| TC-DF-T-01-004-09 | Edge | Race: org bị disable giữa lúc alice đang gọi API | alice gọi API với JWT, đồng thời admin disable org | Request đang chạy hoàn tất hoặc 403 (depending on phase); request kế tiếp 403 ORG_DISABLED |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (runtime entrypoint).

**Chặn:** DF-T-01-002 (cần bảng users có org_id), DF-T-01-003 (RBAC trong org), DF-T-01-009 (member mgmt). Cross-Epic: mọi bảng nghiệp vụ DF-E-02-11 phải kế thừa `TenantScopedModel` — đặc biệt DF-T-02-001 (device registry).

**Phụ thuộc giữa Epic:** Định contract `TenantScopedModel` cho mọi Epic downstream.

**Rủi ro:**

- **R1 — Bug cross-tenant rò dữ liệu.** Tác động: critical, vi phạm hợp đồng B2B. Giảm thiểu: ORM default filter + CI smoke + grep test cho mọi route nghiệp vụ.
- **R2 — Background job không có TenantContext.** Giảm thiểu: strict mode + ADR ghi rõ pattern "với background job phải set context explicitly".
- **R3 — Performance: thêm WHERE clause vào mọi query.** Giảm thiểu: index (org_id, ...) standard pattern; benchmark p99 acceptable.

**Phụ thuộc bên ngoài:** SQLAlchemy ≥ 2.0 (event listener API), PostgreSQL ≥ 14.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85% cho `device_farm/tenancy/*`.
- [ ] Tất cả 9 test case automation.
- [ ] ADR-002 merged.
- [ ] `docs/modules/platform-runtime.md` mục Tenancy cập nhật.
- [ ] CI `cross-tenant-smoke` xanh 5 PR liên tiếp.
- [ ] Performance test: thêm WHERE org_id không làm query > 10% latency baseline.
- [ ] Logger redact `org_id` không nhạy cảm nhưng audit log phải có để truy vết.
- [ ] Security review từ Platform Engineer.
- [ ] Documentation cho dev: "Khi viết route nghiệp vụ, làm gì để tránh leak cross-tenant".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — FR-01-05, FR-01-13.
- **Ma trận năng lực:** "Multi-tenancy theo organization" — Active.
- **Nhóm người dùng:** Admin tổ chức, Platform Engineer.
- **Thuật ngữ:** Organization.
- **ADR liên quan:** ADR-002 (sẽ tạo trong ticket) — "Shared schema multi-tenancy".
- **Risk control:** GDPR data isolation, ISO 27001 access control.
