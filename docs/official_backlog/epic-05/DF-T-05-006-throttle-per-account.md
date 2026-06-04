# DF-T-05-006 — Throttle per account (rate limit theo account social)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-006 |
| **Title** | Throttle per account — giới hạn rate schedule_run trên mỗi account social |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Scheduling |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | `Done` |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:contract`, `type:feature`, `risk:platform-tos`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-05-01 (mở rộng), gap concurrency mục 8 |
| **Truy vết — UC refs** | UC-05-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Throttle per device (DF-T-05-005) bảo vệ phần cứng. Throttle per **account social** (FB, TikTok, ...) bảo vệ tài sản nghiệp vụ — account quá nhiều hành động liên tiếp sẽ bị nền tảng flag/ban (checkpoint trên FB, shadow-ban trên TikTok). Đây là risk legal/ToS rất thực tế cho khách hàng B2B.

Đặc tả module mục 8 không nói rõ throttle account nhưng đề cập "gap concurrency" và rủi ro account safety. Lộ trình nhắc Instagram có rủi ro checkpoint cao. Ticket này build cơ chế:

- Mỗi account có `max_runs_per_hour`, `max_runs_per_day` (mặc định theo platform — vd Instagram = 10/h, Facebook = 30/h, TikTok = 20/h).
- Schedule cố trigger account đã đạt rate limit → defer hoặc reject.
- Operator có dashboard "account nào sắp đụng limit".

P1 vì ảnh hưởng trực tiếp tỷ lệ account sống — KPI nghiệp vụ B2B quan trọng. SP 5 vì có rate limiter (sliding window) phức tạp hơn counter đơn giản của DF-T-05-005.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** giới hạn số lần schedule run trên mỗi account social trong một giờ/ngày
> **Để** tránh account bị checkpoint, shadow-ban, hoặc rate-limit bởi nền tảng

## 4. Yêu cầu chức năng

- Hệ thống PHẢI duy trì rate limiter sliding window per account (1 giờ, 24 giờ).
- Hệ thống PHẢI cho phép cấu hình rate limit ở 3 cấp ưu tiên (cao → thấp): per-account override, platform default (FB/TikTok/Threads/Instagram), organization default.
- Hệ thống PHẢI kiểm tra rate trước khi dispatch — nếu vượt, schedule_run status="throttled_account_rate".
- Hệ thống PHẢI hỗ trợ mode `defer` (đợi window slide) và `reject`.
- Hệ thống PHẢI emit metric `account.rate_limit.utilization` (0-1) cho dashboard "sắp đụng limit".
- Hệ thống PHẢI cho phép platform default được override theo profile rủi ro: Instagram=10/h, Facebook=30/h.
- Hệ thống PHẢI tracking accurate rate kể cả khi schedule_run fail (vẫn count một lần dispatch).
- Hệ thống PHẢI từ chối schedule cố ý vượt limit khi tạo (vd schedule cron `* * * * *` trên IG account = 60/h > 10/h limit).
- Hệ thống PHẢI emit event `schedule.run.throttled.account` để notification.
- Hệ thống PHẢI cho phép Fleet Operator + Social Data Operator query "top accounts nearing limit" qua API.
- Hệ thống PHẢI handle account multi-platform (1 account nhiều platform sẽ có rate riêng per platform).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Throttle IG account vượt 10/h**

```
Given account A platform=instagram, đã 10 schedule_run trong 60 phút qua
And schedule S nhắm A, throttle_mode="defer"
When tick lúc T
Then schedule_run R status="deferred_account_rate", deferred_until=T + (window_slide)
And khi window slide tới <10 trong 60 phút, R tự dispatch
```

**AC-2: Throttle reject mode**

```
Given account A FB rate 30/h, đạt 30 schedule_run trong 60 phút
And schedule S throttle_mode="reject"
When tick
Then schedule_run R status="throttled_account_rate_rejected"
And event schedule.run.throttled.account phát
```

**AC-3: Per-account override**

```
Given account A IG có override max_runs_per_hour=5 (thấp hơn default 10)
When schedule_run thứ 6 trong giờ
Then bị throttle, dù chưa đạt platform default 10
```

**AC-4: Validate schedule tạo vượt limit**

```
Given account A IG rate=10/h
When POST schedule cron="* * * * *" (60 lần/giờ) target_account=A
Then 400 "SCHEDULE_RATE_EXCEEDS_ACCOUNT_LIMIT"
And gợi ý cron giãn hơn (vd `*/6 * * * *` = 10/h)
```

**AC-5: Multi-platform account**

```
Given account A có 2 platform (FB + IG); FB rate=30/h, IG rate=10/h
And 9 schedule_run trong giờ vừa qua trên IG (chưa đạt 10)
And 25 schedule_run trên FB (chưa đạt 30)
When tick mới cho IG
Then dispatch bình thường (chỉ count IG bucket)
```

**AC-6: Edge — sliding window biên**

```
Given account A IG, schedule_run lúc 12:00:00 (count=10 đạt limit)
When tick lúc 13:00:00 (đúng 1h sau)
Then schedule_run lúc 12:00 đã rơi khỏi window → tick dispatch được
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm anti-detection / human pattern simulation — DF-E-07/8 quyết định.
- KHÔNG bao gồm auto-cooldown khi account bị checkpoint (cần DF-E-07 hiểu signal).
- KHÔNG bao gồm UI dashboard rate utilization — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `scheduling.throttle.account` với sliding window Redis ZSET.
- [ ] Platform default config table.
- [ ] Validate schedule rate vs account limit khi POST/PATCH.
- [ ] API `GET /accounts/{id}/rate-utilization`.

**Contract / API** (`layer:contract`)

- [ ] Schedule POST/PATCH chấp nhận `account_throttle_mode` (defer/reject).
- [ ] Schedule_run response thêm `throttle_reason="account_rate"`.
- [ ] Mã lỗi `SCHEDULE_RATE_EXCEEDS_ACCOUNT_LIMIT`.

**Database / Migration** (`layer:db`)

- [ ] Bảng `platform_rate_defaults(platform, max_per_hour, max_per_day)`.
- [ ] Cột override `max_runs_per_hour`, `max_runs_per_day` trên `accounts` (DF-E-07 sở hữu nhưng ticket này add migration).

**Infra / DevOps** (`layer:infra`)

- [ ] Redis ZSET `account:{id}:platform:{p}:runs_window`.
- [ ] TTL 24h tự cleanup.

**Documentation** (`layer:docs`)

- [ ] Doc rate default per platform + cảnh báo Instagram cao rủi ro.
- [ ] Doc cách Operator điều chỉnh override.

**Test** (`layer:test`)

- [ ] Unit test sliding window.
- [ ] Test 3 cấp ưu tiên override.
- [ ] Test multi-platform isolated bucket.
- [ ] Edge: biên window.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-05-006-01 | Positive | IG account, 10 runs trong 1h | Tick mới defer mode | Deferred, auto dispatch khi window slide |
| TC-DF-T-05-006-02 | Positive | FB account override=20, 20 runs | Tick reject mode | throttled_account_rate_rejected |
| TC-DF-T-05-006-03 | Positive | Account 2 platform, FB busy, IG free | Tick IG | Dispatch IG bình thường |
| TC-DF-T-05-006-04 | Negative | Cron `* * * * *` (60/h) trên IG (rate 10/h) | POST schedule | 400 SCHEDULE_RATE_EXCEEDS_ACCOUNT_LIMIT |
| TC-DF-T-05-006-05 | Negative | Override > platform default mà không có permission | POST account | 403 |
| TC-DF-T-05-006-06 | Edge | Run lúc 12:00, tick lại lúc 13:00:00 exact | Wait | Window slide chính xác, dispatch ok |
| TC-DF-T-05-006-07 | Edge | Account bị xoá sau khi deferred | Wait dispatch | Schedule_run cancel với lý do "account_deleted" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-05-002, DF-E-07 (account entity).

**Chặn:** DF-T-05-007 (fairness layer).

**Phụ thuộc giữa Epic:** DF-E-07 sở hữu account entity và account-platform binding; DF-E-08 cung cấp platform metadata.

**Rủi ro:**

- **Rate limit default sai cho platform mới:** mỗi platform mới Active → cần update default; có thể quên. Giảm thiểu: default conservative (5/h) khi không có entry; alert nếu platform mới không có default.
- **Multi-tenant account share:** account A dùng cho org X và org Y → rate count chung hay riêng? Quyết định: chung per account (count tổng), audit log ai trigger.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] TC mapped.
- [ ] Platform default seeded cho 4 platform.
- [ ] Doc cảnh báo IG rủi ro cao.
- [ ] Metric utilization exposed.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — mục 8 concurrency gap.
- **Thuật ngữ:** Rate limit, Sliding window, Account.
- **Nhóm người dùng:** Social Data Operator.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — Instagram L2 + cảnh báo account safety.
