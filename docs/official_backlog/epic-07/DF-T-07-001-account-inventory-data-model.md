# DF-T-07-001 — Account inventory data model + CRUD

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-001 |
| **Title** | Account inventory data model + CRUD |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2`, `risk:auth` |
| **Truy vết — FR refs** | FR-07-01, FR-07-09, FR-07-14 |
| **Truy vết — UC refs** | UC-07-01 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module định nghĩa account là "tài nguyên user-scoped với platform, username, status, tag, metadata, usage_counter, và proxy_id tùy chọn — đầy đủ thông tin để quản lý fleet tài khoản." Trước đây các đội tự lưu account trong Google Sheet hoặc script Python; không có khả năng query, không có owner rõ ràng, không enforce tenant isolation. Ticket này dựng data model trung tâm cho mọi ticket khác trong Epic.

Persona hưởng lợi: Social Data Operator (quản lý fleet account), Automation Builder (tham chiếu account trong scenario), Fleet Operator (xem account-device mapping).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** tạo / đọc / cập nhật / xóa account với đầy đủ trường nghiệp vụ (platform, username, status, tag, metadata, proxy_id, usage_counter) và mọi truy cập đều enforced theo organization
> **Để** fleet account được quản lý tập trung, đúng tenant, không phải dùng Google Sheet nữa

Persona phụ: Platform Engineer (đảm bảo schema dùng được cho cả 4 platform target).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI lưu bảng `accounts` với các cột: `id`, `organization_id`, `owner_id`, `platform` (facebook/tiktok/threads/instagram/other), `username`, `external_id` (id account phía platform khi biết), `status` (xem DF-T-07-005 FSM), `tag` (text/json), `metadata` (JSONB tự do, KHÔNG chứa credential), `usage_counter` (bigint default 0), `proxy_id` (FK nullable), `last_used_at`, `last_status_check_at`, `created_at`, `updated_at`, `deleted_at` (soft-delete) — trace FR-07-01, FR-07-09.
- Hệ thống PHẢI enforce unique constraint theo `(organization_id, platform, username)` khi `username` non-null.
- Hệ thống PHẢI enforce unique theo `(organization_id, platform, external_id)` khi `external_id` non-null (dùng cho dedup khi bulk import).
- Hệ thống PHẢI cung cấp REST endpoint:
  - `POST /api/accounts` tạo account.
  - `GET /api/accounts/{id}` đọc.
  - `PATCH /api/accounts/{id}` update field cho phép (KHÔNG cho update organization_id).
  - `DELETE /api/accounts/{id}` soft-delete.
  - `GET /api/accounts` list với filter (chi tiết ở DF-T-07-013).
- Hệ thống PHẢI enforce organization filter mặc định mọi query — trace FR-07-14.
- Hệ thống PHẢI từ chối truy cập account ngoài organization với 404 (không leak existence) — trace FR-07-14.
- Hệ thống PHẢI tách rõ "Account" với "Device" — không dùng tên field/UI trùng — trace FR-07-13.
- Hệ thống PHẢI cung cấp cờ flag `credential_schema_version` trong metadata để Epic biết cookie/session storage đang theo phiên bản nào (chuẩn bị cho DF-T-07-004).
- Hệ thống NÊN log mọi tạo/xóa account vào audit (DF-T-07-011).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo account thành công**

```
Given user U thuộc org X có quyền data-operator
When U POST /api/accounts với { platform:"facebook", username:"user_a", tag:"project-A" }
Then trả 201 với account_id mới
And account có owner_id=U, organization_id=X, status="active" (default), usage_counter=0
```

**AC-2: Unique constraint**

```
Given org X đã có account (facebook, "user_a")
When U POST tạo lại với cùng (facebook, "user_a")
Then trả 409 ACCOUNT_DUPLICATE
And không có account mới được tạo
```

**AC-3: Cross-tenant**

```
Given account A thuộc org X
When user thuộc org Y GET /api/accounts/{A.id}
Then trả 404 (không leak)
And audit log entry "cross_tenant_attempt"
```

**AC-4: Update không cho đổi organization**

```
Given user U owner account A trong org X
When U PATCH /api/accounts/{A.id} với { organization_id: Y }
Then trả 422 IMMUTABLE_FIELD_REJECTED
And account A vẫn org X
```

**AC-5: Soft-delete**

```
Given account A đang được scenario S tham chiếu
When U DELETE /api/accounts/{A.id}
Then trả 200 với cờ soft_deleted=true
And bảng accounts row vẫn còn với deleted_at non-null
And scenario S vẫn truy vết được account A (chỉ không xuất hiện trong list default)
And nếu scenario chạy mới với A → fail rõ ràng ACCOUNT_DELETED
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm cookie/session secure storage — đó là DF-T-07-004.
- KHÔNG bao gồm state FSM transitions — đó là DF-T-07-005.
- KHÔNG bao gồm bulk import — đó là DF-T-07-010.
- KHÔNG bao gồm device_accounts link — đó là DF-T-07-012.
- KHÔNG bao gồm group binding — đó là DF-T-07-003.
- KHÔNG bao gồm search nâng cao — đó là DF-T-07-013.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Model ORM `Account`.
- [ ] Repository `AccountRepository` (create, get, update, soft_delete) với organization filter mặc định.
- [ ] Service `AccountService` validate input + check unique.
- [ ] 4 REST endpoint cơ bản.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI account schema + mã lỗi: `ACCOUNT_DUPLICATE`, `ACCOUNT_NOT_FOUND`, `IMMUTABLE_FIELD_REJECTED`, `CROSS_TENANT_DENIED`, `ACCOUNT_DELETED`.

**Database / Migration** (`layer:db`)

- [ ] Migration tạo bảng `accounts` với toàn bộ cột §4.
- [ ] Index (organization_id, platform, username) unique.
- [ ] Index (organization_id, platform, external_id) unique partial khi external_id NOT NULL.
- [ ] Index (organization_id, owner_id), (organization_id, status).

**Documentation** (`layer:docs`)

- [ ] ERD trong `docs/modules/accounts.md`.
- [ ] Cập nhật `docs/official_docs/modules/07-accounts-and-groups.md` link tới ticket.
- [ ] Mục thuật ngữ "Account" verify khớp.

**Test** (`layer:test`)

- [ ] Unit test repository.
- [ ] Integration test 4 endpoint.
- [ ] Test unique constraint, cross-tenant, soft-delete.
- [ ] Load test 100k account / org.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-07-001-01 | Positive | User U có quyền | POST /api/accounts {platform, username, tag} | 201; account tạo; owner=U |
| TC-DF-T-07-001-02 | Positive | Account A trong org X | GET /api/accounts/{A.id} với user same org | 200; trả đầy đủ field; không leak credential |
| TC-DF-T-07-001-03 | Negative | (facebook, "user_a") đã tồn tại | POST cùng | 409 ACCOUNT_DUPLICATE |
| TC-DF-T-07-001-04 | Negative | Cross-org access | GET account của org khác | 404; audit log |
| TC-DF-T-07-001-05 | Edge | metadata JSON 5 MB | POST với metadata oversize | 422 METADATA_TOO_LARGE (cap 256 KB) |
| TC-DF-T-07-001-06 | Edge | Soft-delete account A; sau đó POST tạo cùng (platform, username) | POST | 201 thành công (deleted_at != null nên unique partial cho phép) |
| TC-DF-T-07-001-07 | Edge | 100k account / org; list query | GET với filter | Latency p95 < 1s; pagination chuẩn |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-E-01 (organization scope + JWT auth).

**Chặn:** DF-T-07-002, DF-T-07-003, DF-T-07-004, DF-T-07-005, DF-T-07-010, DF-T-07-012, DF-T-07-013.

**Phụ thuộc giữa Epic:** DF-E-01 cung cấp organization_id + JWT user_id; DF-E-06 sẽ join account_id với content_items.

**Rủi ro:**

- **Schema metadata tự do dễ chứa credential plaintext:** giảm thiểu: DF-T-07-004 chuyển credential ra storage tách biệt; cảnh báo trong tài liệu; chấp nhận giai đoạn chuyển tiếp.
- **Migration trên DB production có account cũ:** giảm thiểu: backfill schema từ bảng cũ (nếu có); script verify.

**Phụ thuộc bên ngoài:** DF-E-01 (auth + tenant).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] 4 endpoint qua integration test pass.
- [ ] Cross-tenant test pass với 2 org thật.
- [ ] Load test 100k account: latency p95 < 1s.
- [ ] `docs/modules/accounts.md` ERD viết.
- [ ] Telemetry: `account_total{platform, status, org}`, `account_create_total{result}`.
- [ ] Code review ≥ 1 approve owner module + 1 approve owner DB.
- [ ] Changelog ghi nhận "Account inventory data model phiên bản 1".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md §5.1, §6 FR-07-01, FR-07-09, FR-07-14](../../official_docs/modules/07-accounts-and-groups.md).
- **Nhóm người dùng:** Social Data Operator (§3.1).
- **Thuật ngữ:** [Account](../../official_docs/00-glossary.md), [Organization](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-01, DF-E-06.
