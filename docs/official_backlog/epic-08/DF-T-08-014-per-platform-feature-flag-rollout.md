# DF-T-08-014 — Per-platform feature flag & rollout

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-014 |
| **Title** | Per-platform feature flag & rollout — bật/tắt platform extension theo organization |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Ready |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:agnostic`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-14 |
| **Truy vết — UC refs** | UC-08-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi có 4 platform extension (Facebook Active + 3 Draft target) cùng nạp vào Device Farm, team không muốn 3 platform Draft tự động khả dụng cho mọi organization — pilot user có thể nhầm Draft với Active và xây workflow dựa trên handler scaffolding. Cần cơ chế **per-platform feature flag theo organization**: Facebook default ON cho mọi org; TikTok / Threads / Instagram default OFF, chỉ bật cho pilot org được Product cho phép.

Ticket này thêm bảng `org_platform_flags` (org_id, platform, enabled, enabled_by, enabled_at) và logic check ở scenario dispatch — nếu org không bật platform tương ứng, scenario chứa step `<platform>_*` bị reject với mã lỗi rõ ràng. Đồng thời, có endpoint admin để Product team bật platform cho pilot org và xem ai đang dùng platform nào.

Persona hưởng lợi: **Platform Engineer** (rollout có kiểm soát), **Product/Admin** (quyết định ai pilot platform Draft), **Automation Builder** (không bị surprise khi platform Draft không hoạt động như Active).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer (hoặc Admin team)
> **Tôi muốn** bật/tắt từng platform extension theo organization
> **Để** Facebook Active mặc định mọi org dùng, 3 platform Draft chỉ bật cho pilot org và không gây kỳ vọng sai

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có bảng `org_platform_flags` (org_id, platform, enabled, enabled_by, enabled_at, notes) — trace FR-08-14.
- Hệ thống PHẢI seed default: Facebook = ON cho mọi org; TikTok / Threads / Instagram = OFF cho mọi org.
- Hệ thống PHẢI check flag khi dispatch scenario; scenario chứa step `<platform>_*` của platform OFF bị reject với mã `PLATFORM_NOT_ENABLED_FOR_ORG`.
- Hệ thống PHẢI expose endpoint `GET /api/social-ext/orgs/{org_id}/platforms` trả về flag state cho org đó.
- Hệ thống PHẢI expose endpoint `POST /api/social-ext/orgs/{org_id}/platforms/{platform}/enable` (role `platform-admin`) bật platform cho org.
- Hệ thống PHẢI expose endpoint `POST /api/social-ext/orgs/{org_id}/platforms/{platform}/disable` tắt platform.
- Hệ thống PHẢI ghi audit log cho mọi thay đổi flag.
- Frontend Builder PHẢI hide step type của platform OFF khỏi flow editor cho org đó.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Default Facebook ON, TikTok OFF cho org mới**

```
Given org mới "acme" được tạo
When admin gọi GET /api/social-ext/orgs/acme/platforms
Then response chứa {facebook: enabled=true, tiktok: enabled=false, threads: enabled=false, instagram: enabled=false}
And không cần migration thủ công
```

**AC-2: Reject scenario step platform OFF**

```
Given org "acme" có TikTok = OFF
And user của org dispatch scenario chứa step `tiktok_open_video_comments`
When scenario qua dispatcher
Then dispatcher reject với mã `PLATFORM_NOT_ENABLED_FOR_ORG`
And error message ghi rõ "tiktok is not enabled for organization acme. Contact admin to enable."
And scenario không được lưu vào queue
```

**AC-3: Bật platform cho pilot org**

```
Given admin có role `platform-admin`
And org "pilot-co" chưa bật TikTok
When admin gọi POST /api/social-ext/orgs/pilot-co/platforms/tiktok/enable với note "pilot Q3"
Then flag tiktok cho pilot-co chuyển ON
And audit log ghi "tiktok enabled for pilot-co by user X at T, note: pilot Q3"
And scenario tiktok của org pilot-co dispatch được
```

**AC-4: Frontend hide platform OFF**

```
Given Automation Builder của org "acme" mở flow editor
When họ filter platform
Then thấy Facebook trong list (ON), không thấy TikTok/Threads/Instagram (OFF)
And nếu họ paste scenario JSON chứa step tiktok thì save bị reject với mã `PLATFORM_NOT_ENABLED_FOR_ORG`
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI dashboard quản lý flag — sẽ ở DF-E-11.
- KHÔNG bao gồm tự động bật platform khi platform chuyển từ Draft sang Active (chỉ default mới flip ON, org cũ giữ nguyên flag) — sẽ là migration script khi chuyển trạng thái.
- KHÔNG bao gồm cấu hình per-user (chỉ per-org) — không trong scope.
- KHÔNG bao gồm A/B testing variant theo platform — không trong scope.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement check flag trong scenario dispatcher (trước khi enqueue)
- [ ] Implement endpoint enable/disable
- [ ] Implement audit log integration

**Database / Migration** (`layer:db`)

- [ ] Tạo bảng `org_platform_flags` (org_id, platform, enabled, enabled_by, enabled_at, notes, updated_at)
- [ ] Index trên (org_id, platform) unique
- [ ] Seed migration: Facebook ON cho mọi org hiện hữu, 3 platform khác OFF

**Contract / API** (`layer:contract`)

- [ ] GET /api/social-ext/orgs/{org_id}/platforms
- [ ] POST .../enable và .../disable
- [ ] OpenAPI spec
- [ ] Authentication: role `platform-admin` cho enable/disable, role any user cho GET (chỉ thấy org mình)

**Frontend** (`layer:frontend`)

- [ ] Filter platform list theo flag state trong flow editor
- [ ] Hint message khi user paste step platform OFF

**Documentation** (`layer:docs`)

- [ ] Tài liệu rollout playbook cho Platform Engineer
- [ ] Cập nhật onboarding checklist cho pilot org

**Test** (`layer:test`)

- [ ] Unit test flag check trong dispatcher
- [ ] Integration test: bật/tắt và verify scenario behavior
- [ ] Audit log test

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-014-01 | Positive | Org "acme" mới | GET /api/social-ext/orgs/acme/platforms | Facebook enabled=true; 3 platform khác enabled=false |
| TC-DF-T-08-014-02 | Positive | Admin role `platform-admin` | POST enable TikTok cho org "pilot-co" | Flag ON; audit log ghi; scenario tiktok dispatch được |
| TC-DF-T-08-014-03 | Negative | Org "acme" có TikTok OFF | User dispatch scenario step `tiktok_open_video_comments` | Reject với `PLATFORM_NOT_ENABLED_FOR_ORG`; scenario không vào queue |
| TC-DF-T-08-014-04 | Negative | User không có role `platform-admin` | Gọi POST enable | Response 403; audit log ghi attempted unauthorized |
| TC-DF-T-08-014-05 | Edge | Scenario nested chứa step platform OFF ở scenario con | Dispatch parent | Reject với mã rõ ràng, chỉ rõ scenario con và step nào vi phạm |
| TC-DF-T-08-014-06 | Edge | Org có Facebook OFF (đặc biệt do compliance) | User dispatch scenario `fb_like_post` | Reject; nhắc admin xem tại sao Facebook bị disable cho org này |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-002, DF-T-08-003.

**Chặn:** DF-T-08-006 (rollout scenario template tới pilot org), DF-T-08-009/011/013 (3 platform Draft chỉ thực sự dùng được sau khi org bật).

**Phụ thuộc giữa Epic:**

- **DF-E-01 (Platform & Auth)** — role `platform-admin` phải có trong RBAC.
- **DF-E-09 (Notifications & Analytics)** — audit log dùng activity_logger của DF-E-09.
- **DF-E-04 (Campaign)** — scenario dispatcher gắn flag check ở Module Campaign.

**Rủi ro:**

- **Migration seed sai làm Facebook tắt cho org cũ** → giảm thiểu: migration có dry-run, review SQL trước apply.
- **Flag check tăng latency dispatcher** → giảm thiểu: cache flag theo org, TTL 60s; metric latency.
- **Builder copy scenario từ org có TikTok ON sang org OFF, bị reject sau khi đã build** → giảm thiểu: hint khi import scenario.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] Tất cả TC-DF-T-08-014-* map sang test tự động.
- [ ] Tài liệu rollout playbook cập nhật.
- [ ] OpenAPI spec cho 3 endpoint mới đã commit.
- [ ] Migration seed đã chạy dry-run trên staging.
- [ ] Telemetry: metric `platform_flag_check_latency`, audit log per change.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi rõ default flag và cách bật cho pilot org.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-14), mục 7 (Ma trận năng lực per-platform).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Platform Engineer, Admin.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Organization.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — Per-platform rollout.
