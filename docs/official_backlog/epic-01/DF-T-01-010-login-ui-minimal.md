# DF-T-01-010 — Login UI minimal & dashboard shell

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-010 |
| **Title** | Login UI tối thiểu, dashboard shell, banner safe mode |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `module:frontend`, `layer:frontend`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-01, FR-01-02, FR-01-10 |
| **Truy vết — UC refs** | UC-01-01, UC-01-02, UC-01-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Frontend cần một entrypoint tối thiểu để team có thể đăng nhập và test các module nghiệp vụ DF-E-02+. Ticket này không build dashboard đầy đủ (DF-E-11 lo) mà chỉ build (1) trang login dùng `/api/auth/login`, lưu token vào localStorage hoặc httpOnly cookie; (2) auto-refresh token khi sắp expire; (3) shell layout có header, sidebar trống (chờ DF-E-11 fill), banner safe mode dựa `/api/server/status`; (4) logout button; (5) trang `/me` xem thông tin tài khoản.

Mục đích chính: **không block DF-E-02+** khi cần UI để thao tác. Khi DF-E-11 chạy, ticket đó sẽ rebuild dashboard đầy đủ với design system; ticket này chỉ là MVP wireframe.

P1 vì không cần ngay từ ngày 1 nhưng cần trước khi UAT DF-E-02 (device list cần login).

## 3. Câu chuyện người dùng

> **Là** người vận hành
> **Tôi muốn** đăng nhập qua trang web, token tự động refresh, thấy thông tin tài khoản và org của tôi
> **Để** bắt đầu sử dụng dashboard mà không phải dùng curl

> **Là** Admin tổ chức
> **Tôi muốn** thấy banner màu khi hệ thống đang ở safe mode
> **Để** biết tại sao một số chức năng tạm không hoạt động

## 4. Yêu cầu chức năng

- Hệ thống PHẢI trang `/login` với form username + password, gọi `POST /api/auth/login` — trace FR-01-01.
- Hệ thống PHẢI lưu access token và refresh token an toàn (httpOnly cookie cho refresh, in-memory hoặc localStorage cho access — quyết định: httpOnly cookie cho refresh, memory cho access).
- Hệ thống PHẢI auto-refresh access token khi còn 60s đến expire — trace FR-01-02.
- Hệ thống PHẢI route guard: trang khác `/login`/`/accept-invite` yêu cầu authenticated, redirect về `/login` nếu không.
- Hệ thống PHẢI shell layout: header (logo, user menu, logout), sidebar (placeholder), content area.
- Hệ thống PHẢI banner safe mode (màu vàng) hiển thị khi `/api/server/status` trả `safe_mode: true` — trace FR-01-10.
- Hệ thống PHẢI trang `/me` hiển thị username, email, org name, roles, last_login_at.
- Hệ thống PHẢI trang `/accept-invite?token=...` đón flow accept invite (DF-T-01-009).
- Hệ thống PHẢI gửi header `X-Request-Id` (UUID) cho mỗi request để correlate với backend log (DF-T-01-008).
- Hệ thống PHẢI redirect về `/dashboard` (shell trống) sau login thành công.
- Hệ thống NÊN hiển thị error message rõ ràng khi login fail (không lộ user tồn tại hay không).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Login thành công và redirect**

```
Given alice có account trong DB
When alice mở /login, nhập username + password đúng, bấm Submit
Then frontend gọi POST /api/auth/login
And nhận access + refresh token, lưu đúng cách (httpOnly cho refresh)
And redirect tới /dashboard
And header hiển thị "alice (Acme)"
```

**AC-2: Login fail hiển thị error**

```
Given alice nhập sai mật khẩu
When submit
Then frontend nhận 401 INVALID_CREDENTIALS
And hiển thị message "Sai thông tin đăng nhập" (không "user not found")
And không redirect; vẫn ở /login
```

**AC-3: Auto-refresh access token**

```
Given alice đã login, access token TTL 15 phút
When 14 phút trôi qua, frontend timer trigger
Then frontend gọi POST /api/auth/refresh với refresh token (httpOnly cookie)
And nhận access token mới
And user không bị logout, không phải nhập lại password
```

**AC-4: Route guard redirect về /login**

```
Given user chưa login
When user nhập URL /dashboard hoặc /me trực tiếp
Then frontend redirect về /login?next=/dashboard
And sau login, redirect về /dashboard
```

**AC-5: Banner safe mode hiển thị**

```
Given backend đang safe mode (/api/server/status trả safe_mode:true)
When alice mở dashboard
Then banner màu vàng ở top hiển thị "Hệ thống đang ở chế độ giới hạn. Auto-refresh trong 30s..."
And mỗi 30s polling lại; khi safe_mode chuyển false → banner ẩn
```

**AC-6: Logout xóa token và refresh cookie**

```
Given alice đã login
When alice click Logout
Then frontend gọi POST /api/auth/logout
And xóa access token in-memory
And refresh cookie bị clear (server set Set-Cookie với Max-Age=0)
And redirect /login
```

**AC-7: Accept invite từ link email**

```
Given alice nhận email với link /accept-invite?token=xyz
When alice click link
Then form hiển thị "Đặt tên đăng nhập và mật khẩu"
And alice nhập, submit; nhận 200 và auto-login
And redirect /dashboard
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm full dashboard với device list, campaign, etc. — DF-E-11.
- KHÔNG bao gồm design system, theme, accessibility audit — DF-E-11.
- KHÔNG bao gồm SSO button — out of scope module.
- KHÔNG bao gồm forgot password flow — defer ticket riêng (DF-T-11-XXX).
- KHÔNG bao gồm 2FA — đưa vào lộ trình sau.
- KHÔNG bao gồm i18n đa ngôn ngữ — defer DF-E-11.
- KHÔNG bao gồm mobile responsive đầy đủ — chỉ desktop ở MVP này.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] (Endpoint đã có từ DF-T-01-002, DF-T-01-007, DF-T-01-009.)
- [ ] Đảm bảo CORS config cho domain frontend.
- [ ] Đảm bảo /api/auth/refresh set httpOnly cookie đúng SameSite, Secure.

**Frontend** (`layer:frontend`)

- [ ] Project setup: React + TypeScript + Vite + generated client từ OpenAPI (DF-T-01-001 artifact).
- [ ] Auth context provider (token state, refresh timer).
- [ ] Component LoginForm, AcceptInviteForm.
- [ ] Component ShellLayout (header + sidebar + content).
- [ ] Component SafeModeBanner polling /api/server/status mỗi 30s.
- [ ] Route guard wrapper.
- [ ] Page /me.
- [ ] X-Request-Id interceptor.

**Contract / API** (`layer:contract`)

- [ ] Đảm bảo OpenAPI spec đầy đủ cho 4 endpoint dùng.
- [ ] CORS contract docs.

**Database / Migration** (`layer:db`)

- [ ] Không có.

**Infra / DevOps** (`layer:infra`)

- [ ] Helm chart cho frontend (NGINX serving static build).
- [ ] Ingress route `/` → frontend, `/api/*` → backend.
- [ ] Helm value `frontend.api_base_url`.

**Documentation** (`layer:docs`)

- [ ] `docs/frontend/auth-flow.md` — sequence diagram.
- [ ] Storybook chú thích cho component (defer DF-E-11 nếu chưa setup).

**Test** (`layer:test`)

- [ ] Unit test AuthContext (timer, refresh, logout).
- [ ] Component test LoginForm (Vitest + Testing Library).
- [ ] E2E test (Playwright) cho 7 AC.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-010-01 | Positive | alice account active | Truy cập /login, nhập đúng, submit | Redirect /dashboard, header có "alice (Acme)" |
| TC-DF-T-01-010-02 | Positive | alice login 14 phút trước, access token sắp expire | Chờ auto-refresh | Token mới được cấp, user vẫn online, không bị logout |
| TC-DF-T-01-010-03 | Positive | Backend safe mode | Mở dashboard | Banner vàng hiển thị; sau khi backend lên lại, banner ẩn trong 30s |
| TC-DF-T-01-010-04 | Positive | alice click logout | Click | Cookie cleared, redirect /login, gọi lại /api/me trả 401 |
| TC-DF-T-01-010-05 | Negative | alice nhập sai mật khẩu | Submit | Error message generic "Sai thông tin đăng nhập"; không lộ user tồn tại |
| TC-DF-T-01-010-06 | Negative | Chưa login, direct URL /dashboard | Truy cập URL | Redirect /login?next=/dashboard |
| TC-DF-T-01-010-07 | Negative | Token đã expire và refresh fail (revoked) | Frontend gọi API | Logout tự động, redirect /login với message "Phiên hết hạn" |
| TC-DF-T-01-010-08 | Edge | Frontend mất kết nối backend (offline) | Mở dashboard | Hiển thị placeholder "Mất kết nối, retry trong 10s"; không crash |
| TC-DF-T-01-010-09 | Edge | 2 tab cùng login khác user | Login user khác ở tab 2 | Cả 2 tab vẫn hoạt động độc lập (nếu dùng memory token); nếu cookie xung đột → quyết định: refresh cookie chỉ active user gần nhất, tab cũ sẽ auto-logout sau khi access expire |
| TC-DF-T-01-010-10 | Edge | URL /accept-invite?token=expired | Mở link | Hiển thị message "Lời mời hết hạn, yêu cầu admin mời lại"; không crash |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (helm + OpenAPI artifact), DF-T-01-002 (auth endpoint), DF-T-01-007 (server status), DF-T-01-009 (accept invite endpoint).

**Chặn:** DF-E-02 UAT (cần UI), DF-E-11 (đây là baseline shell sẽ extend).

**Phụ thuộc giữa Epic:** Generated TypeScript client từ DF-T-01-001 artifact.

**Rủi ro:**

- **R1 — Access token lưu localStorage rò qua XSS.** Giảm thiểu: memory only cho access token; refresh httpOnly cookie. CSP header chặn inline script.
- **R2 — Auto-refresh race khi multiple tab.** Giảm thiểu: BroadcastChannel sync giữa tab.
- **R3 — Banner safe mode polling quá thường gây load.** Giảm thiểu: 30s interval default; tắt khi tab background.

**Phụ thuộc bên ngoài:** React ≥ 18, Vite, generated client.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 70% frontend.
- [ ] 10 test case automation (E2E Playwright).
- [ ] Đã deploy lên staging, login flow chạy end-to-end.
- [ ] CSP header config có; XSS scan clean.
- [ ] Telemetry: frontend gửi event `login.success`, `login.failed`, `auth.refresh.auto` về backend.
- [ ] Documentation auth flow updated.
- [ ] Code review từ Frontend lead.
- [ ] Lighthouse perf score ≥ 80 cho login page.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — FR-01-01, FR-01-02, FR-01-10.
- **Ma trận năng lực:** "JWT user authentication" — Active.
- **Nhóm người dùng:** Mọi persona vận hành (login dashboard).
- **Thuật ngữ:** JWT, Refresh token.
- **Lộ trình:** M1 Infrastructure Bootstrap; full dashboard ở DF-E-11.
