# DF-T-08-003 — Plugin lifecycle (load / unload / version)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-003 |
| **Title** | Plugin lifecycle — load / unload / version migration cho platform extension |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Ready |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:agnostic`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-04, FR-08-14, FR-08-15 |
| **Truy vết — UC refs** | UC-08-04, UC-08-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi một platform extension đã chạy trong production, Platform Engineer cần ba thao tác vòng đời: **load** (nạp khi cài extension mới), **unload** (gỡ tạm để debug hoặc khi extension bị thu hồi), **version migration** (upgrade extension lên phiên bản mới hoặc rollback). Nếu không có lifecycle API, mọi thay đổi phải restart toàn bộ Device Farm — không khả thi với fleet đang chạy hàng nghìn campaign.

Ticket này hiện thực hóa lifecycle API + cơ chế version compatibility check. Khi nâng cấp Facebook extension từ v1.0.0 lên v1.1.0, registry phải kiểm tra rằng các scenario đang chạy tham chiếu step legacy `tap_fb_comment_button` vẫn dispatch đúng về handler mới — bảo vệ FR-08-04 (legacy alias).

Persona hưởng lợi chính: **Platform Engineer** (operations day-2 trên extension), **Operator** (không bị disruption khi nâng cấp).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** load, unload, và migrate version platform extension qua API mà không restart Device Farm
> **Để** vận hành extension như component thay thế được, không phải full deployment cycle khi vá bug platform-specific

## 4. Yêu cầu chức năng

- Hệ thống PHẢI expose endpoint `POST /api/social-ext/platforms/{platform}/load` để nạp extension không cần restart — trace FR-08-14.
- Hệ thống PHẢI expose endpoint `POST /api/social-ext/platforms/{platform}/unload` để gỡ extension, dừng chấp nhận step mới của platform đó.
- Hệ thống PHẢI giữ scenario đang chạy với handler version cũ tới khi xong, không kill nửa chừng khi unload.
- Hệ thống PHẢI hỗ trợ version migration: extension v1.0.0 → v1.1.0 trong cùng platform, validate compatibility (SemVer rule).
- Hệ thống PHẢI giữ legacy alias hoạt động sau khi nâng cấp version — trace FR-08-04.
- Hệ thống PHẢI ghi audit log cho mọi lifecycle event (ai load, lúc nào, từ version nào sang version nào).
- Hệ thống NÊN expose endpoint `GET /api/social-ext/platforms/{platform}/version-history` để xem lịch sử version.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Load extension không restart**

```
Given Device Farm đang chạy, registry chưa có TikTok extension
And admin upload TikTok extension package v0.1.0
When admin gọi POST /api/social-ext/platforms/tiktok/load
Then registry nạp TikTok v0.1.0
And metric `plugin_registry_active_platforms` tăng 1
And không có scenario đang chạy bị disruption
And audit log ghi "tiktok loaded by user X at T"
```

**AC-2: Unload không kill scenario đang chạy**

```
Given Facebook extension đang nạp, có 5 scenario đang chạy step `fb_tap_comment_button`
When admin gọi POST /api/social-ext/platforms/facebook/unload
Then 5 scenario tiếp tục chạy tới hết với handler hiện tại
And scenario mới dispatch step `fb_tap_comment_button` bị reject với mã lỗi `PLATFORM_UNLOADED`
And metric `plugin_registry_active_platforms` giảm 1 sau khi 5 scenario xong
```

**AC-3: Version migration giữ legacy alias**

```
Given Facebook v1.0.0 đã nạp, step canonical `fb_tap_comment_button` và legacy alias `tap_fb_comment_button` đều dispatch về cùng handler
When admin migrate Facebook lên v1.1.0
Then registry chuyển sang handler mới
And cả `fb_tap_comment_button` và `tap_fb_comment_button` vẫn dispatch về handler v1.1.0
And test guard chạy verify legacy alias dispatch đúng
```

**AC-4: Reject migration không tương thích SemVer**

```
Given Facebook v1.0.0 đang nạp
And admin upload package "Facebook v2.0.0" (major bump → breaking change)
When admin gọi migrate qua API
Then registry reject với mã `PLUGIN_INCOMPATIBLE_MAJOR_BUMP`
And error message yêu cầu unload v1 → load v2 thay vì migrate
And audit log ghi attempt fail
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI dashboard quản lý extension — sẽ ở DF-E-11.
- KHÔNG bao gồm tự động download extension từ registry trung tâm (chỉ upload thủ công) — chưa trong lộ trình.
- KHÔNG bao gồm cluster-wide rollout (tất cả replica cùng lúc) — sẽ phụ thuộc deployment infra DF-E-01.
- KHÔNG bao gồm cấu hình rollout per organization — sẽ xử lý trong DF-T-08-014.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Cài đặt `PluginLifecycleManager` với 3 method: `load(package)`, `unload(platform)`, `migrate(platform, newVersion)`
- [ ] Cài đặt SemVer compatibility checker
- [ ] Cài đặt in-flight scenario tracking để defer unload
- [ ] Cài đặt legacy alias preservation logic trong migration
- [ ] Tích hợp với audit log (DF-E-09 dependency)

**Contract / API** (`layer:contract`)

- [ ] POST /api/social-ext/platforms/{platform}/load (multipart upload package)
- [ ] POST /api/social-ext/platforms/{platform}/unload
- [ ] POST /api/social-ext/platforms/{platform}/migrate
- [ ] GET /api/social-ext/platforms/{platform}/version-history
- [ ] Authentication: yêu cầu role `platform-admin`

**Database / Migration** (`layer:db`)

- [ ] Tạo bảng `platform_extension_versions` (id, platform, version, loaded_at, unloaded_at, loaded_by, package_hash)
- [ ] Index theo (platform, loaded_at DESC)

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/modules/social-ext-contract.md` mục lifecycle
- [ ] Tutorial "Vận hành extension day-2"

**Test** (`layer:test`)

- [ ] Unit test SemVer compatibility checker
- [ ] Integration test load/unload không restart
- [ ] Integration test legacy alias preservation qua migration
- [ ] E2E test: 5 scenario đang chạy, unload, verify scenario tiếp tục xong

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-003-01 | Positive | Device Farm đang chạy, chưa có TikTok | Upload TikTok v0.1.0 và gọi load API | TikTok nạp thành công; registry active; audit log ghi event |
| TC-DF-T-08-003-02 | Positive | Facebook v1.0.0 nạp, scenario `fb_tap_comment_button` chạy được | Migrate Facebook lên v1.1.0; chạy lại scenario cùng step và legacy alias `tap_fb_comment_button` | Cả 2 alias đều dispatch về handler v1.1.0 thành công |
| TC-DF-T-08-003-03 | Negative | Facebook v1.0.0 nạp, 3 scenario đang chạy | Unload Facebook | 3 scenario hoàn thành; scenario mới bị reject `PLATFORM_UNLOADED` |
| TC-DF-T-08-003-04 | Negative | Facebook v1.0.0 nạp | Migrate lên v2.0.0 (major bump) | Reject với `PLUGIN_INCOMPATIBLE_MAJOR_BUMP`; yêu cầu unload trước |
| TC-DF-T-08-003-05 | Edge | 100 scenario đang chạy step Facebook | Unload Facebook → đo thời gian tới khi metric về 0 | Tất cả scenario hoàn tất; no zombie state; audit log đầy đủ |
| TC-DF-T-08-003-06 | Edge | User không có role `platform-admin` | Gọi load API | Response 403; audit log ghi attempted unauthorized |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002.

**Chặn:** DF-T-08-014.

**Phụ thuộc giữa Epic:**

- **DF-E-01 (Platform & Auth)** — role `platform-admin` phải tồn tại trong RBAC.
- **DF-E-09 (Notifications & Analytics)** — audit log infrastructure dùng activity_logger của DF-E-09.

**Rủi ro:**

- **Memory leak khi load/unload nhiều lần** → giảm thiểu: unit test stress 100 cycle load/unload, monitor process RSS.
- **Race condition: 2 admin migrate cùng lúc** → giảm thiểu: lock per-platform, second request bị reject với `PLUGIN_MIGRATION_IN_PROGRESS`.
- **Legacy alias mất sau migration do handler mới quên đăng ký** → giảm thiểu: contract require extension declare `legacy_aliases` field, registry tự động re-bind.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả test case TC-DF-T-08-003-* map sang test tự động.
- [ ] Tài liệu kỹ thuật cập nhật.
- [ ] OpenAPI spec cho 4 endpoint mới đã commit.
- [ ] Telemetry: audit log per lifecycle event.
- [ ] Code review ≥ 1 approve từ owner module.
- [ ] Stress test 100 cycle load/unload pass.
- [ ] Release notes / changelog cập nhật.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-04, FR-08-14, FR-08-15), mục 8 (giới hạn legacy alias).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Platform Engineer.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Legacy alias.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
