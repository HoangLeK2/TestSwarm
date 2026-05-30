# DF-T-08-011 — Threads handler draft

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-011 |
| **Title** | Threads handler draft — khung `threads_open_post_replies` + scaffolding like/follow/repost (Draft target) |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:social-ext`, `layer:backend`, `type:feature`, `platform:threads`, `coverage:L2`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-08-01, FR-08-03, FR-08-08, FR-08-10, FR-08-12 |
| **Truy vết — UC refs** | UC-08-02, UC-08-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Threads handler chưa có code production. Để parser Threads (DF-T-08-010) có ngữ cảnh UI khi extract reply chain, cần step action `threads_open_post_replies` ở mức tối thiểu. Đồng thời, scaffolding cho like/follow/repost đặt sẵn để Platform Engineer có template khi lộ trình đẩy Threads sang Active.

Ticket này tạo **handler draft**: 1 step action thật `threads_open_post_replies`, các step like/follow/repost là scaffolding raise `NOT_IMPLEMENTED`. Coverage chưa hoàn chỉnh.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** một handler Threads draft với step `threads_open_post_replies` chạy được + scaffolding cho like/follow/repost
> **Để** parser Threads có ngữ cảnh UI đúng và có template handler khi chuyển Active

## 4. Yêu cầu chức năng

- Hệ thống PHẢI implement step `threads_open_post_replies` thật, mở reply panel của post hiện tại — trace FR-08-01.
- Hệ thống PHẢI đăng ký scaffolding step `threads_like_post`, `threads_follow_user`, `threads_repost_post` raise `NOT_IMPLEMENTED` — trace FR-08-01.
- Hệ thống PHẢI áp dụng UI-gated semantic — trace FR-08-12.
- Hệ thống PHẢI yêu cầu account runtime; warning log khi thiếu — trace FR-08-10.
- Hệ thống PHẢI thu evidence (screenshot trước + sau) cho step thật.
- Hệ thống PHẢI cập nhật `docs/official_docs/platforms/threads.md` known gaps liệt kê handler chưa implement — trace FR-08-03.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: `threads_open_post_replies` hoạt động**

```
Given device mở Threads ở 1 post
And scenario chứa step `threads_open_post_replies`
When scenario chạy
Then handler tap reply icon, UI verify panel reply hiện
And StepResult.success với evidence
And step extract sau đó có ngữ cảnh reply-list
```

**AC-2: Scaffolding raise NOT_IMPLEMENTED**

```
Given scenario chứa step `threads_repost_post`
When chạy
Then raise `THREADS_HANDLER_NOT_IMPLEMENTED`
And error message pointing tới docs/official_docs/platforms/threads.md
```

**AC-3: UI-gated fail chặn step sau**

```
Given step `threads_open_post_replies` fail (reply icon không có)
And step kế `extract threads_comments`
When chạy
Then step 1 fail; step 2 KHÔNG dispatch
And scenario fail-fast
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm implementation thật cho like/follow/repost — khi chuyển Active.
- KHÔNG bao gồm frontend node, scenario template.
- KHÔNG bao gồm L3 guardrail.
- KHÔNG bao gồm phân biệt Threads vs Instagram ở UI level đầy đủ — chỉ best-effort.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement `ThreadsOpenPostRepliesHandler`
- [ ] Đăng ký scaffolding `threads_like_post`, `threads_follow_user`, `threads_repost_post`
- [ ] Implement evidence capture, UI-gated check
- [ ] Implement account requirement warning log

**Contract / API** (`layer:contract`)

- [ ] JSON schema cho step params

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/official_docs/platforms/threads.md` known gaps

**Test** (`layer:test`)

- [ ] Unit test handler thật
- [ ] Test scaffolding raise đúng error
- [ ] Integration test open_replies → extract threads_comments

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-011-01 | Positive | Device mở Threads ở 1 post | Scenario chạy `threads_open_post_replies` | Reply panel hiện; success; evidence đầy đủ |
| TC-DF-T-08-011-02 | Positive | Step open_replies xong | Step kế `extract threads_comments` | Parser chạy với ngữ cảnh đúng |
| TC-DF-T-08-011-03 | Negative | Scenario chứa `threads_like_post` | Chạy | Raise `THREADS_HANDLER_NOT_IMPLEMENTED`; message rõ ràng |
| TC-DF-T-08-011-04 | Negative | Device không mở Threads | Scenario chạy `threads_open_post_replies` | Step fail UI mismatch; step sau không dispatch |
| TC-DF-T-08-011-05 | Edge | Reply panel mở với 0 reply | Chạy step | Success vẫn được; step extract sau parse list rỗng; không crash |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-001, DF-T-08-002, DF-T-08-010.

**Chặn:** Future Threads Active milestone.

**Phụ thuộc giữa Epic:**

- **DF-E-04 (Campaign)** — UI-gated.
- **DF-E-07 (Account)** — account resolution khi handler thật được implement.

**Rủi ro:**

- **Builder dùng scaffolding step như thật** → giảm thiểu: error message rõ ràng, frontend badge "scaffolding".
- **Threads UI thay đổi theo update Meta** → giảm thiểu: regression test hàng tuần.

**Phụ thuộc bên ngoài:** Threads Android app phiên bản tested.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 70%.
- [ ] Tất cả TC-DF-T-08-011-* map sang test tự động.
- [ ] Tài liệu `docs/official_docs/platforms/threads.md` cập nhật.
- [ ] Ma trận năng lực ghi handler status "Draft".
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi rõ status draft.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — mục 6.
- **Platform profile:** [threads.md](../../official_docs/platforms/threads.md).
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md).
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md).
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md).
