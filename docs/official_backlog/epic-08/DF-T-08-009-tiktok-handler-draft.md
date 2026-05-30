# DF-T-08-009 — TikTok handler draft

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-009 |
| **Title** | TikTok handler draft — khung `tiktok_open_video_comments` + scaffolding like/follow (Draft target) |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:tiktok`, `coverage:L2`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-01, FR-08-03, FR-08-08, FR-08-10, FR-08-12 |
| **Truy vết — UC refs** | UC-08-02, UC-08-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

TikTok handler hiện chưa có code production. Để parser TikTok (DF-T-08-008) có ngữ cảnh UI đúng (vd mở comment panel của 1 video trước khi extract comment), cần step action `tiktok_open_video_comments` ở mức tối thiểu. Đồng thời, khung scaffolding cho like/follow đặt sẵn để Platform Engineer có template khi chuyển TikTok sang Active.

Ticket này tạo **handler draft** ở mức tối thiểu: 1 step action thật `tiktok_open_video_comments`, các step like/follow là scaffolding (đăng ký step type, raise `NOT_IMPLEMENTED` ở runtime để Builder không nhầm với handler thật). Coverage chưa hoàn chỉnh — chưa có evidence pipeline, chưa có UI verify state change đầy đủ, chưa có account safety policy.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một handler TikTok draft với step `tiktok_open_video_comments` chạy được + scaffolding like/follow
> **Để** parser TikTok có ngữ cảnh UI đúng và có template handler khi chuyển Active

## 4. Yêu cầu chức năng

- Hệ thống PHẢI implement step `tiktok_open_video_comments` thật, mở comment panel của video hiện tại — trace FR-08-01.
- Hệ thống PHẢI đăng ký scaffolding step `tiktok_like_video`, `tiktok_follow_user`, `tiktok_share_video` raise `NOT_IMPLEMENTED` ở runtime — trace FR-08-01.
- Hệ thống PHẢI áp dụng UI-gated semantic mặc định cho step thật — trace FR-08-12.
- Hệ thống PHẢI yêu cầu account runtime khi step cần login; chưa enforce nhưng có warning log — trace FR-08-10.
- Hệ thống PHẢI thu evidence (screenshot trước + sau) cho step thật.
- Hệ thống PHẢI cập nhật `docs/official_docs/platforms/tiktok.md` mục known gaps liệt kê handler chưa implement — trace FR-08-03.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: `tiktok_open_video_comments` hoạt động**

```
Given device mở TikTok ở 1 video
And scenario chứa step `tiktok_open_video_comments`
When scenario chạy
Then handler tap icon comment, UI verify panel comment hiện
And StepResult.success với evidence screenshot trước/sau
And step extract sau đó có ngữ cảnh comment-list
```

**AC-2: Scaffolding like raise NOT_IMPLEMENTED**

```
Given scenario chứa step `tiktok_like_video`
When chạy
Then handler raise `TIKTOK_HANDLER_NOT_IMPLEMENTED`
And error message: "tiktok_like_video is scaffolded draft — implementation pending, see docs/official_docs/platforms/tiktok.md"
And không thử thực thi blindly
```

**AC-3: UI-gated fail chặn step sau**

```
Given step `tiktok_open_video_comments` fail (icon không tìm thấy)
And step kế tiếp `extract tiktok_comments`
When chạy
Then step 1 fail; step 2 KHÔNG dispatch
And scenario fail-fast
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm implementation thật cho like/follow/share — sẽ là khi chuyển TikTok Active.
- KHÔNG bao gồm frontend node — chỉ ưu tiên Facebook hiện tại.
- KHÔNG bao gồm scenario template TikTok.
- KHÔNG bao gồm L3 guardrail.
- KHÔNG bao gồm account safety policy chi tiết.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `TikTokOpenVideoCommentsHandler` thật
- [ ] Đăng ký scaffolding handler `tiktok_like_video`, `tiktok_follow_user`, `tiktok_share_video` raise `NOT_IMPLEMENTED`
- [ ] Implement evidence capture
- [ ] Implement UI-gated check
- [ ] Implement account requirement warning log

**Contract / API** (`layer:contract`)

- [ ] JSON schema cho step params

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/platforms/tiktok.md` known gaps
- [ ] Ghi rõ step nào đã implement, step nào scaffolding

**Test** (`layer:test`)

- [ ] Unit test handler thật
- [ ] Test scaffolding raise đúng error
- [ ] Integration test full path: open_video_comments → extract tiktok_comments

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-009-01 | Positive | Device mở TikTok ở 1 video | Scenario chạy `tiktok_open_video_comments` | Comment panel hiện; success; evidence đầy đủ |
| TC-DF-T-08-009-02 | Positive | Step open_comments xong | Step kế `extract tiktok_comments` | Parser chạy với ngữ cảnh đúng; trả comment list |
| TC-DF-T-08-009-03 | Negative | Scenario chứa `tiktok_like_video` | Chạy | Raise `TIKTOK_HANDLER_NOT_IMPLEMENTED`; error message rõ ràng pointing tới docs |
| TC-DF-T-08-009-04 | Negative | Device không mở TikTok | Scenario chạy `tiktok_open_video_comments` | Step fail với UI mismatch; step sau không dispatch |
| TC-DF-T-08-009-05 | Edge | Comment icon vừa render thì biến mất (UI dynamic) | Chạy | Retry với UI-gated check; nếu vẫn fail thì raise rõ ràng |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002, DF-T-08-008.

**Chặn:** Future TikTok Active milestone.

**Phụ thuộc giữa Epic:**

- **DF-E-04 (Campaign)** — UI-gated semantic, error policy.
- **DF-E-07 (Account)** — account resolution khi handler thật cho like/follow được implement.

**Rủi ro:**

- **Builder dùng scaffolding step thấy như thật** → giảm thiểu: error message rõ ràng + log warning khi đăng ký step scaffolding + frontend hiển thị badge "scaffolding".
- **TikTok UI khác giữa locale** → giảm thiểu: ghi rõ locale tested trong profile.

**Phụ thuộc bên ngoài:** TikTok Android app phiên bản tested.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 70%.
- [ ] Tất cả TC-DF-T-08-009-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/tiktok.md` cập nhật.
- [ ] Ma trận năng lực ghi handler status "Draft" cho TikTok.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi rõ status draft.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6.
- **Platform profile:** [tiktok.md](../../official_docs/platforms/tiktok.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md).
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
