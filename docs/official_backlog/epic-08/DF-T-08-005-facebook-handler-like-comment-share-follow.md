# DF-T-08-005 — Facebook handler: like / comment / share / follow

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-005 |
| **Title** | Facebook handler — like / comment / share / follow + canonical `fb_*` + legacy alias `tap_fb_*` |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P0 |
| **Story Points** | 8 |
| **Status** | Ready |
| **Labels** | `module:social-ext`, `layer:backend`, `layer:frontend`, `type:feature`, `platform:facebook`, `coverage:L2`, `persona:platform-engineer`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-08-01, FR-08-03, FR-08-04, FR-08-07, FR-08-10, FR-08-11, FR-08-12, FR-08-15 |
| **Truy vết — UC refs** | UC-08-02, UC-08-04, UC-08-05, UC-08-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Cho tới hiện tại, Facebook handler trong code production có một step duy nhất `tap_fb_comment_button` (legacy naming) với hành vi "miss-tolerant" — fail step không chặn step phía sau, ngược lại pattern UI-gated của module Campaign. Đồng thời, Facebook chưa có handler cho like, share, follow ở mức step type platform-specific; Automation Builder phải dùng `tap_selector` generic và tự đoán selector — dễ vỡ khi FB đổi UI.

Ticket này hoàn thiện bộ handler Facebook chính: **like / comment / share / follow** dưới naming canonical `fb_*`, đồng thời giữ legacy alias `tap_fb_comment_button` dispatch về cùng handler để không vỡ scenario cũ. Mỗi step handler là UI-gated mặc định (fail chặn step phía sau trừ khi có `retry` / `branch` / `ignore_error` tường minh). Frontend flow editor có node tương ứng để Automation Builder kéo thả thay vì tự gõ selector.

Persona hưởng lợi: **Automation Builder** (dựng scenario Facebook rõ ràng), **Platform Engineer** (template handler cho platform khác), **Social Data Operator** (workflow crawl có thể engage trước khi extract).

Đọc nhanh cho dev: ticket này xây các step handler Facebook canonical `fb_*` và giữ alias legacy `tap_fb_comment_button`. Điểm quan trọng là UI-gated mặc định, account runtime config bắt buộc cho action cần login, evidence trước/sau step và backward compatibility cho scenario cũ.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** kéo thả các step Facebook canonical `fb_like_post`, `fb_comment_post`, `fb_share_post`, `fb_follow_user`, `fb_tap_comment_button` trong flow editor
> **Để** dựng scenario Facebook rõ ràng, có legacy alias tương thích, và không phải tự đoán selector khi FB đổi UI

## 4. Yêu cầu chức năng

- Hệ thống PHẢI implement step type canonical: `fb_like_post`, `fb_comment_post`, `fb_share_post`, `fb_follow_user`, `fb_tap_comment_button` — trace FR-08-01.
- Hệ thống PHẢI giữ legacy alias `tap_fb_comment_button` dispatch về cùng handler `fb_tap_comment_button` — trace FR-08-04.
- Hệ thống PHẢI dùng content type qualified `fb_post`, `fb_comment` khi handler tạo content liên quan (vd `fb_comment_post` ghi comment đã đăng vào content_items) — trace FR-08-03.
- Hệ thống PHẢI áp dụng UI-gated semantic mặc định cho mọi step Facebook mới — fail chặn step phía sau, chỉ relax khi `retry` / `branch` / `ignore_error` được khai báo — trace FR-08-12.
- Hệ thống PHẢI yêu cầu account runtime config khi step cần login (vd `fb_like_post` cần account); thiếu account báo lỗi cấu hình rõ ràng — trace FR-08-10.
- Hệ thống PHẢI có frontend flow editor node cho 5 step trên — trace FR-08-11.
- Hệ thống PHẢI thu evidence (screenshot trước + sau action) cho mọi step Facebook để debug.
- Hệ thống PHẢI giữ backward compatibility cho scenario cũ dùng `tap_fb_comment_button` — trace FR-08-15.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Step canonical `fb_like_post` hoạt động UI-gated**

```
Given device đã login Facebook và đang ở 1 post
And scenario chứa step `fb_like_post` với target post_id = X
When scenario chạy
Then handler tap Like button đúng post X
And UI verify nút Like đã chuyển sang "Liked"
And step trả về StepResult.success với evidence screenshot trước/sau
And step kế tiếp được dispatch
```

**AC-2: Legacy alias `tap_fb_comment_button` dispatch về handler canonical**

```
Given scenario cũ dùng step name `tap_fb_comment_button`
And Facebook handler v1.0.0 đã nạp với canonical `fb_tap_comment_button`
When scenario chạy
Then alias resolver convert `tap_fb_comment_button` → `fb_tap_comment_button`
And dispatch về cùng handler instance
And log info "legacy alias resolved: tap_fb_comment_button → fb_tap_comment_button"
And step thực thi đúng hành vi mở comment list
```

**AC-3: Thiếu account khi step yêu cầu login**

```
Given scenario chứa step `fb_comment_post` với text = "hello"
And scenario config không khai báo account runtime
When scenario chạy tới step đó
Then handler báo lỗi cấu hình `FB_HANDLER_ACCOUNT_REQUIRED`
And error message ghi rõ "fb_comment_post requires account runtime config"
And không có fallback ngầm chọn account khác
And scenario bị mark fail tại step đó
```

**AC-4: UI-gated fail chặn step phía sau**

```
Given scenario có 3 step: [fb_like_post, fb_share_post, save_extraction]
And step 1 (fb_like_post) fail vì button không tìm thấy
When scenario chạy
Then step 1 trả về StepResult.fail với evidence
And step 2 (fb_share_post) KHÔNG được dispatch
And step 3 KHÔNG được dispatch
And scenario kết thúc fail-fast
And artifact đầy đủ cho step 1
```

**AC-5: Frontend flow editor có node cho 5 step**

```
Given Automation Builder mở flow editor
When họ filter platform = Facebook
Then 5 node hiển thị: fb_like_post, fb_comment_post, fb_share_post, fb_follow_user, fb_tap_comment_button
And mỗi node có form params khớp schema backend
And kéo thả node vào canvas tạo scenario step hợp lệ
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm step extract — đã xử lý trong DF-T-08-004.
- KHÔNG bao gồm login flow (handler giả định device đã login) — thuộc DF-E-07 (Account & Session).
- KHÔNG bao gồm OTP/captcha handling — thuộc DF-E-07.
- KHÔNG bao gồm step Facebook Story (story view, story reply) — chưa trong L2 scope.
- KHÔNG bao gồm step messaging (Facebook Messenger) — không trong scope module này.
- KHÔNG bao gồm L3 guardrail cho 5 step — sẽ xử lý trong DF-T-08-007.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `FbLikePostHandler`, `FbCommentPostHandler`, `FbSharePostHandler`, `FbFollowUserHandler`
- [ ] Refactor `tap_fb_comment_button` legacy handler → canonical `fb_tap_comment_button` + alias resolver
- [ ] Implement evidence capture (before/after screenshot, hierarchy snapshot)
- [ ] Implement UI-gated check sau action (verify state change)
- [ ] Implement account requirement validation (fail-fast khi thiếu account)
- [ ] Đăng ký 5 step vào registry qua contract DF-T-08-001
- [ ] Implement alias resolver `tap_fb_comment_button` → `fb_tap_comment_button`

**Frontend** (`layer:frontend`)

- [ ] Thêm 5 node Facebook vào flow editor palette
- [ ] Form params cho mỗi node khớp schema backend (target post_id, comment text, account ref, ...)
- [ ] Icon Facebook cho 5 node
- [ ] Validation client-side trước khi save scenario

**Contract / API** (`layer:contract`)

- [ ] JSON schema cho 5 step type params
- [ ] OpenAPI spec cho frontend metadata endpoint
- [ ] Alias resolver registration trong contract

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/platforms/facebook.md` mục 5 với bảng step type đầy đủ
- [ ] Tutorial "Dựng scenario Facebook engage + crawl"
- [ ] Ghi rõ deprecation policy cho legacy alias (hỗ trợ thêm 6 tháng sau khi canonical merge)

**Test** (`layer:test`)

- [ ] Unit test per handler với mock device session
- [ ] Test UI-gated semantic (fail step chặn step sau)
- [ ] Test legacy alias dispatch
- [ ] Integration test full scenario: login → like → comment → share → extract
- [ ] E2E test trên thiết bị thật với 3 device
- [ ] Frontend snapshot test cho 5 node

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-005-01 | Positive | Device login FB, đang ở post X | Scenario chạy `fb_like_post` cho post X | Like thành công; UI verify Liked; evidence screenshot trước/sau; StepResult.success |
| TC-DF-T-08-005-02 | Positive | Scenario cũ dùng `tap_fb_comment_button` | Chạy scenario | Alias resolve về `fb_tap_comment_button`; handler chạy thành công; log info alias resolved |
| TC-DF-T-08-005-03 | Negative | Scenario chứa `fb_comment_post`, không khai báo account | Chạy scenario | Fail với `FB_HANDLER_ACCOUNT_REQUIRED`; không tự fallback account; artifact đính kèm |
| TC-DF-T-08-005-04 | Negative | Step 1 `fb_like_post` fail (button không tìm thấy), step 2 `fb_share_post` đứng sau | Chạy scenario | Step 1 fail; step 2 KHÔNG dispatch; scenario fail-fast |
| TC-DF-T-08-005-05 | Edge | Step `fb_like_post` đã được like trước đó (post đang ở state "Liked") | Chạy lại | Handler nhận diện state đã Liked; trả về success idempotent với log info "already liked"; không double-tap |
| TC-DF-T-08-005-06 | Edge | Network chậm, UI verify timeout sau 5s | Chạy `fb_like_post` | Step fail với `FB_HANDLER_UI_VERIFY_TIMEOUT`; evidence đầy đủ; có thể retry qua scenario error policy |
| TC-DF-T-08-005-07 | Edge | Step `fb_follow_user` với userId không tồn tại | Chạy | Handler raise `FB_HANDLER_TARGET_NOT_FOUND`; không silent success |
| TC-DF-T-08-005-08 | Positive | Scenario có cả canonical `fb_tap_comment_button` và legacy `tap_fb_comment_button` ở 2 step khác nhau | Chạy | Cả 2 dispatch về cùng handler; cả 2 step success; behavior nhất quán |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002, DF-T-08-004.

**Chặn:** DF-T-08-006 (scenario library cần handler để build template), DF-T-08-007.

**Phụ thuộc giữa Epic:**

- **DF-E-04 (Campaign / Scenario executor)** — UI-gated semantic và error policy là responsibility executor.
- **DF-E-07 (Account & Account Group)** — account runtime resolution cho step yêu cầu login.
- **DF-E-11 (Frontend)** — flow editor node là phần của frontend module.

**Rủi ro:**

- **Facebook đổi UI làm selector vỡ** → giảm thiểu: selector chiến lược dùng accessibility id thay vì text, regression test hàng tuần.
- **Legacy alias deprecation gây confusion** → giảm thiểu: deprecation cycle 6 tháng có thông báo trên release note; log warning nhưng vẫn dispatch.
- **Account safety (ban từ FB)** → giảm thiểu: handler có rate limit nội tại không cấu hình được runtime (vd max 10 like/phút per account); detail policy ở DF-T-08-007.

**Phụ thuộc bên ngoài:** Phụ thuộc Facebook Android app phiên bản tested.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80% trên handler files.
- [ ] Tất cả TC-DF-T-08-005-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/facebook.md` mục 5 cập nhật.
- [ ] OpenAPI + JSON schema cho 5 step type đã commit.
- [ ] Frontend node hiển thị đúng trong flow editor (DF-E-11 coordination).
- [ ] Telemetry: metric `fb_handler_action_total` (counter theo action type và status), `fb_handler_ui_verify_latency`.
- [ ] Code review ≥ 1 approve từ owner module DF-MOD-08 và DF-MOD-04.
- [ ] Đã chạy thử trên ≥ 5 thiết bị thật ≥ 24h với scenario engage thực.
- [ ] Legacy alias test guard chạy trong CI.
- [ ] Release notes cập nhật, có thông báo deprecation cycle cho alias.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6 (FR-08-01, FR-08-03, FR-08-04, FR-08-10, FR-08-11), mục 8 (legacy alias).
- **Platform profile:** [facebook.md](../../official_docs/platforms/facebook.md) — mục 5 (L2 Active), mục 7 (Account requirement).
- **Module Campaign:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — UI-gated.
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — Automation Builder, Social Data Operator.
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — Legacy alias, UI-gated.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
