# DF-T-11-001 — App shell + navigation + feature folder + generated client

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-001 |
| **Title** | App shell + navigation + feature folder per domain + generated TypeScript client bootstrap |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 8 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `layer:contract`, `layer:infra`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-11-01, FR-11-02, FR-11-03, FR-11-04, FR-11-15 |
| **Truy vết — UC refs** | UC-11-01, UC-11-02, UC-11-14, UC-11-15 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đây là **foundation ticket** của DF-E-11. Mọi ticket UI sau đứng trên: feature folder per domain (FR-11-01), generated TypeScript client từ OpenAPI là cách mặc định gọi backend (FR-11-02), Next API proxy adapter cho route ngoài client (FR-11-03), i18n routing theo `/[locale]/dashboard/...` (FR-11-04), feature-local service module thay ad hoc fetch (FR-11-15). Nếu không có ticket này, các ticket UI sau sẽ phân tán cấu trúc và drift contract.

Persona hưởng lợi chính là **Platform Engineer** — họ là người set up cấu trúc và chịu trách nhiệm khi đội mới onboard. Mọi persona end-user (UC-11-01, UC-11-02) hưởng lợi gián tiếp khi dashboard có navigation rõ ràng và đa ngôn ngữ.

Vị trí trong luồng: sơ đồ "Cách dashboard tiêu thụ backend qua generated client và Next API proxy" (module 11 mục 5.1) và "Bản đồ feature folder theo domain" (mục 5.2).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer (nhánh kỹ thuật) và mọi persona end-user (nhánh trải nghiệm)
> **Tôi muốn** dashboard có cấu trúc feature folder per domain, generated TypeScript client làm chân lý, navigation rõ ràng, và i18n routing
> **Để** thay đổi một feature không lan ra feature khác, contract backend không drift ngầm, và đội đa quốc gia làm việc thoải mái.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI tổ chức code theo feature folder cho mỗi domain: devices, campaigns, scenario-templates, accounts, account-groups, device-groups, content, schedules, notifications, analytics, relay-agents — trace FR-11-01.
- Mỗi feature folder PHẢI có entrypoint rõ + UI + hook + service riêng — trace FR-11-01, FR-11-15.
- Hệ thống PHẢI có pipeline regenerate `DeviceFarmApi.ts` từ `openapi.json` backend, hook vào CI — trace FR-11-02.
- Hệ thống PHẢI có Next API proxy convention: mỗi proxy là một file `app/api/<path>/route.ts` kèm comment lý do tồn tại + issue tracking ref — trace FR-11-03.
- Hệ thống PHẢI có i18n routing pattern `/[locale]/dashboard/...` với ít nhất 2 locale (vi, en) bootstrap — trace FR-11-04.
- Hệ thống PHẢI có navigation shell hiển thị mục đến toàn bộ domain với grouping rõ ràng — trace UC-11-01.
- Code review PHẢI từ chối fetch trực tiếp trong component (lint rule hoặc convention) — trace FR-11-15.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Feature folder structure đầy đủ**

```
Given repo Next.js dashboard
When checkout main và list folder dưới src/features
Then thấy 11 domain folder (devices, campaigns, scenario-templates, accounts, account-groups, device-groups, content, schedules, notifications, analytics, relay-agents)
And mỗi folder có README ngắn + ui/ + hooks/ + service/ subfolder
```

**AC-2: Generated client sync với OpenAPI**

```
Given backend phát hành openapi.json phiên bản mới
When pipeline regenerate chạy
Then DeviceFarmApi.ts cập nhật với endpoints mới
And CI fail nếu DeviceFarmApi.ts out-of-sync với checked-in openapi.json snapshot
```

**AC-3: i18n routing hoạt động**

```
Given user truy cập /vi/dashboard/devices
Then nội dung tiếng Việt
When user đổi sang /en/dashboard/devices
Then nội dung tiếng Anh
And thiếu bản dịch chuỗi mới fallback về en, không vỡ trang
```

**AC-4: Next API proxy có ghi chú lý do**

```
Given có file app/api/notifications-unread/route.ts (proxy)
When code review hoặc CI parity check
Then file có comment block ghi rõ "Reason: notifications route chưa có trong generated client (issue #1234)"
And nếu thiếu comment, CI fail
```

**AC-5: Ad hoc fetch bị chặn**

```
Given developer thêm fetch("/api/foo") trực tiếp trong một component
When chạy lint rule custom
Then lỗi rõ "Use feature service instead of ad hoc fetch (FR-11-15)"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm trang devices / campaigns / content cụ thể — thuộc DF-T-11-003 → DF-T-11-015.
- KHÔNG bao gồm login flow + RBAC — DF-T-11-002.
- KHÔNG bao gồm refactor `control-record-view.tsx` — backlog riêng theo ma trận năng lực.
- KHÔNG bao gồm offline mode — lộ trình.
- KHÔNG bao gồm xử lý dual JWT storage hay Zustand — backlog kỹ thuật.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Scaffold Next.js app với app router + i18n middleware.
- [ ] Tạo skeleton 11 feature folder + README ngắn.
- [ ] Navigation shell + sidebar component.
- [ ] Lint rule chặn ad hoc fetch trong component.
- [ ] i18n bootstrap vi + en + namespace cấu trúc.

**Contract / API** (`layer:contract`)

- [ ] Pipeline generate DeviceFarmApi.ts (script + CI step).
- [ ] CI parity check openapi.json snapshot.

**Infra / DevOps** (`layer:infra`)

- [ ] CI step regenerate client + verify diff.
- [ ] CI step lint rule.

**Documentation** (`layer:docs`)

- [ ] Doc developer guide feature folder + service convention.
- [ ] Doc quy ước Next API proxy + comment template.
- [ ] Doc i18n contribution guide.

**Test** (`layer:test`)

- [ ] Lint rule test.
- [ ] CI parity check test.
- [ ] Smoke test render navigation đúng.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-001-01 | Positive | Repo có 11 feature folder | Build production | Build pass, navigation render đủ 11 mục |
| TC-DF-T-11-001-02 | Positive | openapi.json đồng bộ | Run CI regenerate | Diff 0, CI pass |
| TC-DF-T-11-001-03 | Positive | User truy cập /vi/dashboard và /en/dashboard | Inspect text | Đúng ngôn ngữ tương ứng |
| TC-DF-T-11-001-04 | Negative | Developer thêm fetch("/api/foo") trong component | Run lint | Lỗi rõ ràng |
| TC-DF-T-11-001-05 | Negative | Next API proxy không có comment lý do | Run CI parity check | Fail |
| TC-DF-T-11-001-06 | Edge | Locale param không support (vd /jp/dashboard) | Truy cập | Redirect về locale default + log warning |
| TC-DF-T-11-001-07 | Edge | Backend không có openapi.json (giả lập) | Run regenerate | Fail gracefully với message rõ, không tạo client trống |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** Không (foundation).

**Chặn:** DF-T-11-002 → DF-T-11-015.

**Phụ thuộc giữa Epic:**

- **DF-E-01** — JWT lifecycle, identity (cần endpoint /auth/me cho navigation header).
- Mọi backend Epic — phải có openapi.json ổn định.

**Rủi ro:**

- **Drift OpenAPI:** parity check CI là rào chắn chính.
- **i18n thiếu bản dịch giữa release:** fallback en + tracker missing keys.
- **Lint rule false positive:** allow-list cho legitimate cases (vd next/image).

**Phụ thuộc bên ngoài:** Next.js ≥ 14 app router, OpenAPI generator.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80% trên file thay đổi.
- [ ] Test case TC-DF-T-11-001-* map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter generated_client_regenerate_runs, gauge missing_i18n_keys_per_locale.
- [ ] Code review ≥ 1 approve owner module.
- [ ] Release notes ghi rõ "App shell + feature folder convention + generated client pipeline".
- [ ] Smoke test cross-browser pass.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md §5.1, §5.2 + FR-11-01..04, FR-11-15](../../official_docs/modules/11-frontend-dashboard.md).
- **Nhóm người dùng:** Platform Engineer + mọi persona end-user.
- **Thuật ngữ:** OpenAPI, Generated client, Next API proxy, Feature folder, i18n.
