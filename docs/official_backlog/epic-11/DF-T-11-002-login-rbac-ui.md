# DF-T-11-002 — Login + RBAC UI + i18n bootstrap

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-002 |
| **Title** | Login + RBAC UI — đăng nhập, session, role-based navigation, i18n picker |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `risk:auth`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-11-01, FR-11-04 |
| **Truy vết — UC refs** | UC-11-01, UC-11-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Dashboard không thể public — mọi persona phải login trước. RBAC quyết định nav nào hiện (ví dụ Admin thấy `/admin`, Fleet Operator thấy `/device-farm`, ...). i18n picker cho phép user đổi ngôn ngữ ngay từ login. Module 11 có dual JWT storage (cookie + localStorage) là rủi ro được ghi nhận (mục 8); ticket này KHÔNG giải quyết dual storage (đó là backlog technical debt) — chỉ tiêu thụ JWT từ DF-E-01.

Persona: tất cả persona — không login thì không vào được dashboard.

## 3. Câu chuyện người dùng

> **Là** mọi persona Device Farm
> **Tôi muốn** login một lần, dashboard nhớ session, navigation chỉ hiện mục mà role tôi được phép, và đổi ngôn ngữ tiện lợi
> **Để** vào việc nhanh, không bị nhầm tính năng ngoài quyền, và team đa quốc gia làm việc thoải mái.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có trang `/[locale]/login` nhận username/password (hoặc SSO khi sẵn) — trace FR-11-04.
- Login thành công PHẢI redirect về landing trang theo role hoặc trang trước đó nếu deep link.
- Navigation PHẢI ẩn/hiện mục theo role JWT của user — trace FR-11-01.
- Khi JWT hết hạn, dashboard PHẢI tự refresh hoặc bounce về login với toast lý do.
- Logout PHẢI clear cookie + localStorage (cả 2 — cho đến khi backlog dual JWT giải quyết).
- i18n picker PHẢI có trong header dashboard và trang login; lưu lựa chọn vào cookie + URL prefix — trace FR-11-04.
- Form login PHẢI có UX standard: error message rõ ràng, disable submit khi đang request, password show/hide.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Login thành công flow**

```
Given user có credential hợp lệ
When điền form login + Submit
Then API trả JWT, cookie + localStorage được set
And redirect tới /[locale]/dashboard (landing theo role)
And navigation hiển thị mục mà role được phép
```

**AC-2: RBAC ẩn nav theo role**

```
Given user role "fleet-operator"
When mở dashboard
Then nav hiển thị: Devices, Device groups, Relay agents, Activity log, Notifications
And không hiển thị: Account console, Admin
```

**AC-3: JWT hết hạn**

```
Given user đang ở trang content
When JWT expire
Then dashboard nhận 401 từ API
And bounce về /[locale]/login với toast "Session expired"
And query param `next=` giữ URL gốc để redirect sau login
```

**AC-4: i18n picker đổi ngôn ngữ ngay lập tức**

```
Given user đang ở /vi/dashboard/campaigns
When chọn en từ picker
Then URL chuyển sang /en/dashboard/campaigns
And UI render tiếng Anh
And lựa chọn được lưu cookie
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm SSO/OIDC implementation — DF-E-01.
- KHÔNG bao gồm refactor dual JWT storage — backlog technical debt.
- KHÔNG bao gồm 2FA flow — DF-E-01 sau.
- KHÔNG bao gồm password reset UX — DF-E-01.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Trang `/[locale]/login` với form + validation.
- [ ] Auth hook + service.
- [ ] Navigation shell tiêu thụ role JWT.
- [ ] Interceptor 401 → bounce.
- [ ] i18n picker component.
- [ ] Header user menu (avatar, logout).

**Contract / API** (`layer:contract`)

- [ ] Tiêu thụ endpoint /auth/login, /auth/me, /auth/refresh, /auth/logout từ generated client.

**Documentation** (`layer:docs`)

- [ ] Doc RBAC mapping role → nav items.

**Test** (`layer:test`)

- [ ] E2E test login luồng thành công.
- [ ] Test RBAC ẩn nav.
- [ ] Test refresh / expire JWT.
- [ ] Test i18n picker.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-002-01 | Positive | Credential hợp lệ | Login | Redirect đúng role landing |
| TC-DF-T-11-002-02 | Positive | Role fleet-operator | Login | Nav hiện đúng mục theo role |
| TC-DF-T-11-002-03 | Negative | Credential sai | Login | Error "Invalid credentials" + không lộ user tồn tại hay không |
| TC-DF-T-11-002-04 | Negative | Backend down | Login | Error rõ "Service unavailable", không spinner vô tận |
| TC-DF-T-11-002-05 | Edge | JWT expire khi user đang ở /dashboard/content | Trigger | Bounce login + giữ next= |
| TC-DF-T-11-002-06 | Positive | Đổi locale qua picker | Inspect URL + cookie | URL prefix + cookie đúng locale |
| TC-DF-T-11-002-07 | Edge | Deep link `/en/dashboard/foo` khi chưa login | Truy cập | Bounce login + next=/en/dashboard/foo |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001.

**Chặn:** DF-T-11-003 → DF-T-11-015.

**Phụ thuộc giữa Epic:** **DF-E-01** — auth endpoint, role definition.

**Rủi ro:**

- **Dual JWT storage XSS:** ghi nhận, backlog kỹ thuật riêng; deploy phía sau reverse proxy + CSP chặt.
- **Race refresh token:** debounce + queue request 401.

**Phụ thuộc bên ngoài:** Auth service DF-E-01.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter login_success/fail, counter session_expired_bounce.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-01, FR-11-04 + §8 dual JWT note](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [01-platform-runtime-and-access.md](../../official_docs/modules/01-platform-runtime-and-access.md).
- **Nhóm người dùng:** Tất cả persona.
- **Thuật ngữ:** JWT, i18n.
