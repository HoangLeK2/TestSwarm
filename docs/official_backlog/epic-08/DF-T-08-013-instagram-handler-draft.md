# DF-T-08-013 — Instagram handler draft

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-013 |
| **Title** | Instagram handler draft — khung `ig_open_media_comments` + scaffolding like/follow/save (Draft target) |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:instagram`, `coverage:L2`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-01, FR-08-03, FR-08-08, FR-08-10, FR-08-12 |
| **Truy vết — UC refs** | UC-08-02, UC-08-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Instagram handler chưa có code production. Để parser Instagram (DF-T-08-012) có ngữ cảnh UI khi extract comment, cần step action `ig_open_media_comments` ở mức tối thiểu. Scaffolding cho like/follow/save (Instagram Save tới collection riêng) đặt sẵn cho lộ trình.

Ticket này tạo **handler draft**: 1 step action thật `ig_open_media_comments`, các step like/follow/save là scaffolding raise `NOT_IMPLEMENTED`.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một handler Instagram draft với step `ig_open_media_comments` chạy được + scaffolding like/follow/save
> **Để** parser Instagram có ngữ cảnh UI đúng và có template handler khi chuyển Active

## 4. Yêu cầu chức năng

- Hệ thống PHẢI implement step `ig_open_media_comments` thật, mở comment panel của media hiện tại — trace FR-08-01.
- Hệ thống PHẢI đăng ký scaffolding step `ig_like_media`, `ig_follow_user`, `ig_save_media` raise `NOT_IMPLEMENTED` — trace FR-08-01.
- Hệ thống PHẢI áp dụng UI-gated semantic — trace FR-08-12.
- Hệ thống PHẢI yêu cầu account runtime; warning log khi thiếu — trace FR-08-10.
- Hệ thống PHẢI thu evidence (screenshot trước + sau) cho step thật.
- Hệ thống PHẢI cập nhật `docs/official_docs/platforms/instagram.md` known gaps liệt kê handler chưa implement — trace FR-08-03.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: `ig_open_media_comments` hoạt động**

```
Given device mở Instagram ở 1 media (post hoặc reel)
And scenario chứa step `ig_open_media_comments`
When scenario chạy
Then handler tap comment icon, UI verify panel comment hiện
And StepResult.success với evidence
And step extract sau đó có ngữ cảnh comment-list
```

**AC-2: Scaffolding raise NOT_IMPLEMENTED**

```
Given scenario chứa step `ig_save_media`
When chạy
Then raise `IG_HANDLER_NOT_IMPLEMENTED`
And error message pointing tới docs/official_docs/platforms/instagram.md
```

**AC-3: UI-gated fail chặn step sau**

```
Given step `ig_open_media_comments` fail (icon không tìm thấy)
And step kế `extract ig_comments`
When chạy
Then step 1 fail; step 2 KHÔNG dispatch
And scenario fail-fast
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm implementation thật cho like/follow/save — khi chuyển Active.
- KHÔNG bao gồm step Story (story view, story reply, story DM) — known gap.
- KHÔNG bao gồm frontend node, scenario template, L3 guardrail.
- KHÔNG bao gồm step DM (Instagram Direct).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `InstagramOpenMediaCommentsHandler`
- [ ] Đăng ký scaffolding `ig_like_media`, `ig_follow_user`, `ig_save_media`
- [ ] Implement evidence capture, UI-gated check
- [ ] Implement account requirement warning log

**Contract / API** (`layer:contract`)

- [ ] JSON schema cho step params

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/platforms/instagram.md` known gaps

**Test** (`layer:test`)

- [ ] Unit test handler thật
- [ ] Test scaffolding raise đúng error
- [ ] Integration test open_media_comments → extract ig_comments

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-013-01 | Positive | Device mở Instagram ở 1 post | Scenario chạy `ig_open_media_comments` | Comment panel hiện; success; evidence đầy đủ |
| TC-DF-T-08-013-02 | Positive | Step xong | Step kế `extract ig_comments` | Parser chạy với ngữ cảnh đúng |
| TC-DF-T-08-013-03 | Negative | Scenario chứa `ig_like_media` | Chạy | Raise `IG_HANDLER_NOT_IMPLEMENTED`; message rõ ràng |
| TC-DF-T-08-013-04 | Negative | Device không mở Instagram | Scenario chạy `ig_open_media_comments` | Step fail UI mismatch; step sau không dispatch |
| TC-DF-T-08-013-05 | Edge | Media là reel toàn màn hình, comment icon ở vị trí khác | Chạy | Handler có 2 selector pattern (post grid và reel full); chọn đúng theo media_type; nếu fail thì raise rõ ràng |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002, DF-T-08-012.

**Chặn:** Future Instagram Active milestone.

**Phụ thuộc giữa Epic:**

- **DF-E-04 (Campaign)** — UI-gated.
- **DF-E-07 (Account)** — account resolution khi handler thật được implement.

**Rủi ro:**

- **Builder dùng scaffolding step như thật** → giảm thiểu: error message rõ ràng, frontend badge "scaffolding".
- **Reel vs Post UI khác nhau, selector cần phân biệt** → giảm thiểu: handler có 2 selector pattern theo media_type.
- **Instagram update Reel UI thường xuyên** → giảm thiểu: regression test hàng tuần.

**Phụ thuộc bên ngoài:** Instagram Android app phiên bản tested.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 70%.
- [ ] Tất cả TC-DF-T-08-013-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/instagram.md` cập nhật.
- [ ] Ma trận năng lực ghi handler status "Draft".
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi rõ status draft.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6.
- **Platform profile:** [instagram.md](../../official_docs/platforms/instagram.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md).
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
