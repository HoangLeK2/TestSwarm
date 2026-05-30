# DF-T-11-015 — Admin & audit dashboard UI

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-015 |
| **Title** | Admin & audit dashboard UI — activity history, relay agent ops, org settings, member management, 2FA |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:platform-engineer`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-11-07, FR-11-14 |
| **Truy vết — UC refs** | UC-11-05, UC-11-12, UC-11-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Sau khi mọi domain view đã được dựng (devices, campaigns, content, schedules, accounts, notifications), DF-E-11 cần một surface admin cho **người vận hành cấp tổ chức** — gồm activity log view (FR-11-14, mục 5.5 module 11), relay agent ops (FR-11-07), org settings + member management, và user profile + 2FA setup. Nếu thiếu các view này, Admin tổ chức phải xài SQL hoặc CLI nội bộ để cấu hình — chi phí onboarding cao và không truy vết được.

Ticket này gom các view admin/settings/audit thành một feature folder `admin` thống nhất với các sub-route: `/dashboard/activity-history`, `/dashboard/relay-agents`, `/dashboard/settings/profile`, `/dashboard/settings/organization`, `/dashboard/settings/members`. Logic phân quyền dựa vào role từ DF-E-01 — chỉ user có role `org-admin` hoặc `platform-admin` mới thấy các view sensitive.

Persona hưởng lợi: **Admin tổ chức** (cấu hình org, mời member, xem audit), **Fleet Operator** (xem relay agent status, restart agent), **Platform Engineer** (debug qua activity log), **Mọi user** (cấu hình profile + 2FA).

Đọc nhanh cho dev: ticket này gom admin surface trong dashboard, nhưng không mở rộng thành BI dashboard hay audit tracking mọi click frontend. Phần cần làm là activity history, relay agent ops, org/member settings, profile/2FA và role gating theo DF-E-01.

## 3. Câu chuyện người dùng

> **Là** Admin tổ chức
> **Tôi muốn** một surface admin gom activity history + relay agent ops + org settings + member management + profile/2FA
> **Để** vận hành tổ chức không cần xài CLI hay SQL, và có audit trail rõ ràng cho compliance.

Persona phụ: Fleet Operator (relay ops), Platform Engineer (activity log debug), mọi user (profile + 2FA).

## 4. Yêu cầu chức năng

- `/dashboard/activity-history` PHẢI hiển thị lịch sử event của tổ chức với bộ lọc loại event + khoảng thời gian + persona — trace FR-11-14.
- `/dashboard/relay-agents` PHẢI hiển thị danh sách relay agent với heartbeat, status (online/offline/dead), device đang quản lý, action restart — trace FR-11-07.
- `/dashboard/settings/profile` PHẢI cho phép user xem/sửa profile (display name, email, language) + bật/tắt 2FA — trace UC-11-13.
- `/dashboard/settings/organization` PHẢI hiển thị org metadata, billing reference, default locale — trace UC-11-13.
- `/dashboard/settings/members` PHẢI cho phép Admin mời member mới, assign role, revoke access — trace UC-11-13.
- Activity log view PHẢI phân trang, response < 3 s với top 1000 record (KPI module 11).
- Activity log row PHẢI có deep link về resource gốc (campaign, schedule, device, content) khi target hợp lệ.
- Activity log PHẢI export CSV theo filter hiện tại (kết nối với DF-T-09-013 Audit trail report).
- View settings PHẢI ẩn/show theo role — non-admin không thấy `/settings/organization` và `/settings/members`.
- 2FA setup PHẢI dùng TOTP với QR code, có recovery code khi enable.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Activity history filter + deep link**

```
Given org có 500 activity log entry trong 7 ngày qua
When admin mở /dashboard/activity-history filter event_type="campaign.completed", time_range="last 7 days"
Then danh sách hiển thị các entry phù hợp, phân trang 50/trang
And mỗi row có deep link tới /dashboard/campaigns/{campaign_id}/monitor
When click một row có target_type="campaign"
Then chuyển sang campaign monitor view tương ứng
```

**AC-2: Relay agent ops view**

```
Given org có 3 relay agent, 1 đang offline > 5 phút
When fleet operator mở /dashboard/relay-agents
Then relay offline hiển thị badge "Offline 5m" màu đỏ
And mỗi relay liệt kê device đang quản lý
When fleet operator click "Restart" trên relay offline
Then UI gửi action restart qua API
And toast confirm "Restart command sent"
And activity_log entry "relay.restart_requested" được ghi (qua DF-E-09)
```

**AC-3: Role-based view gating**

```
Given user A có role "operator" (không phải admin)
When user A truy cập /dashboard/settings/members
Then UI hiển thị 403 "You need admin role to access this page"
And navigation menu KHÔNG show entry "Members"
Given user B có role "org-admin"
When user B truy cập cùng route
Then view hiển thị danh sách member + action invite/revoke
```

**AC-4: 2FA setup TOTP**

```
Given user chưa enable 2FA
When user mở /dashboard/settings/profile, click "Enable 2FA"
Then UI hiển thị QR code TOTP secret
When user scan bằng authenticator app + nhập 6-digit code
Then 2FA enabled
And recovery code (10 mã single-use) hiển thị một lần với cảnh báo "Save now"
When user logout và login lại
Then bắt buộc nhập TOTP code sau password
```

**AC-5: Activity log export CSV**

```
Given admin filter activity log "last 30 days, event_type=campaign.*"
When admin click "Export CSV"
Then UI gọi API export (DF-T-09-013), nhận file CSV
And file download có cùng filter đang áp dụng
And tối đa 100k row mỗi lần (theo DoD DF-E-09)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm BI dashboard / phân tích sâu — ngoài phạm vi module 11 (Lộ trình).
- KHÔNG bao gồm frontend audit user action (ghi nhận click) — Lộ trình module 11.
- KHÔNG bao gồm SSO/SAML/OIDC UI — Lộ trình (xem mục 2.4 hardening).
- KHÔNG bao gồm notification channel management (đó là DF-E-09 + sẽ vào DF-T-11-014).
- KHÔNG bao gồm activity log retention setting UI — sẽ cấu hình qua admin API (DF-E-09).

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `admin` với sub-folder activity-history, relay-agents, settings/profile, settings/organization, settings/members.
- [ ] Activity history view: list + filter form + paginator + CSV export button.
- [ ] Relay agents view: table với heartbeat + status badge + restart action.
- [ ] Profile view: form + 2FA enable/disable flow + recovery code modal.
- [ ] Organization view: read-only metadata + edit default locale.
- [ ] Members view: invite form + role assignment + revoke confirm modal.
- [ ] Route guard component dựa vào role từ DF-E-01.

**Contract / API** (`layer:contract`)

- [ ] Generated client cho route activity_log query, relay_agents list/restart, org settings, members CRUD, 2FA enroll.
- [ ] Next API proxy với comment nếu route chưa có trong client.

**Documentation** (`layer:docs`)

- [ ] UX doc các view admin.
- [ ] Tutorial cho admin: "Enable 2FA", "Invite member", "Export audit log".

**Test** (`layer:test`)

- [ ] Test role-based gating cho mọi sub-route.
- [ ] Test 2FA enable flow + recovery code display.
- [ ] Test activity log filter combinations.
- [ ] Test CSV export integration với API DF-E-09.
- [ ] Test relay restart action gửi API + activity_log entry.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-015-01 | Positive | Admin login, org có 500 activity entry | Filter event_type=campaign.completed, last 7 days | Danh sách phân trang đúng; response < 3 s |
| TC-DF-T-11-015-02 | Positive | Activity entry có target_type=campaign | Click row | Chuyển sang campaign monitor view tương ứng |
| TC-DF-T-11-015-03 | Positive | Fleet operator login, 1 relay offline | Click "Restart" trên relay offline | Toast confirm + activity_log entry "relay.restart_requested" |
| TC-DF-T-11-015-04 | Positive | User chưa 2FA | Enable 2FA, scan QR, nhập code đúng | 2FA enabled + recovery code hiển thị một lần |
| TC-DF-T-11-015-05 | Negative | User role=operator | Truy cập /dashboard/settings/members | 403 page; menu entry "Members" không hiển thị |
| TC-DF-T-11-015-06 | Negative | User 2FA enabled, nhập TOTP sai | Login | Error "Invalid code"; retry counter tăng |
| TC-DF-T-11-015-07 | Negative | Admin revoke chính account của mình | Click revoke | UI từ chối "Cannot revoke yourself" |
| TC-DF-T-11-015-08 | Edge | Activity log filter trả 0 record | Apply filter | Empty state "No activity matches filter" thay vì spinner vô tận |
| TC-DF-T-11-015-09 | Edge | Activity log export > 100k row | Click export | Error "Result exceeds export limit, narrow your filter" |
| TC-DF-T-11-015-10 | Edge | Recovery code đã dùng hết, user mất TOTP device | Login | UI hướng dẫn liên hệ admin để reset (không tự bypass) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001, DF-T-11-002.

**Chặn:** Không (ticket polish cuối DF-E-11).

**Phụ thuộc giữa Epic:**

- **DF-E-01 (Platform & Auth)** — role model, 2FA backend, member CRUD API.
- **DF-E-03 (Relay Agent)** — relay status API + restart command.
- **DF-E-09 (Notifications & Analytics)** — activity log query API + audit trail export (DF-T-09-013).

**Rủi ro:**

- **2FA recovery code mất** → user lock out. Giảm thiểu: yêu cầu user xác nhận "Saved" trước khi đóng modal recovery code; có quy trình admin reset 2FA ngoại tuyến.
- **CSV export lớn block UI** → giảm thiểu: async export, gửi link qua notification khi sẵn sàng nếu > 10k row.
- **Role gating bypass qua direct URL** → giảm thiểu: server-side check route, không chỉ ẩn menu.
- **Activity log query chậm với filter rộng** → giảm thiểu: index DB từ DF-E-09, default time range 7 ngày.

**Phụ thuộc bên ngoài:** TOTP library (vd otplib), DF-E-09 audit trail report API.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Test case TC-DF-T-11-015-* map sang test tự động.
- [ ] 5 sub-route (activity-history, relay-agents, profile, organization, members) render đúng theo role.
- [ ] 2FA enable/disable flow đã chạy e2e với authenticator thật.
- [ ] CSV export đã verify với 100k row sample.
- [ ] Tài liệu UX cho admin commit + tutorial "Enable 2FA" / "Invite member" / "Export audit log".
- [ ] Mỗi Next API proxy (nếu có) có comment lý do + issue tracking.
- [ ] Telemetry: counter `admin_view_opened`, `2fa_enabled_total`, `audit_export_requested_total`.
- [ ] Code review ≥ 1 approve từ owner module 11 + 1 approve từ owner Epic-01 (security review cho 2FA flow).
- [ ] Smoke test cross-browser (Chrome, Edge, Safari).

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md](../../official_docs/modules/11-frontend-dashboard.md) — FR-11-07, FR-11-14, mục 5.5 (activity log view + notification panel).
- **Module Auth & RBAC:** [01-platform-runtime-and-access.md](../../official_docs/modules/01-platform-runtime-and-access.md) — role model, 2FA.
- **Module Relay:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md) — relay status + restart.
- **Module Notifications & Analytics:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — activity log query + audit trail report.
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Admin tổ chức, Fleet Operator, Platform Engineer.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Activity log, Organization, RBAC, 2FA, Relay agent.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — mục 2.4 (hardening — SSO/SAML/OIDC, audit frontend action — Lộ trình).
