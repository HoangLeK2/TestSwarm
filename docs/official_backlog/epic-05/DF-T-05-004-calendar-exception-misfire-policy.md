# DF-T-05-004 — Calendar exception (skip date) + misfire policy

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-004 |
| **Title** | Calendar exception (skip date) + misfire policy (catch-up vs skip) |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Scheduling |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | `Done` |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-05-01, FR-05-08, FR-05-09 |
| **Truy vết — UC refs** | UC-05-01 (mở rộng) |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Cron expression diễn đạt được lịch lặp đơn giản (mỗi ngày 8h sáng) nhưng KHÔNG diễn đạt được "mỗi ngày 8h sáng TRỪ ngày nghỉ lễ" hoặc "mỗi giờ TRỪ thời gian bảo trì 02:00-04:00". Operator thực tế cần:

- **Skip date:** danh sách ngày schedule KHÔNG chạy (vd ngày lễ, ngày bảo trì).
- **Skip window:** khoảng thời gian schedule KHÔNG chạy (vd cuối tuần).

Ngoài skip, ticket này định nghĩa **misfire policy** — hành vi khi tick bị miss (farm down lúc 8h sáng, lên lại lúc 8h15): có **catch-up** (chạy bù tick đã miss) hay **skip** (bỏ qua, chỉ chạy tick kế tiếp)? Đặc tả module mục 8 không giải quyết rõ — phải định nghĩa ở đây.

P2 vì là enhancement, không block KPI core 99.5% tick. SP 3 vì re-dùng workflow của DF-T-05-002 — chỉ thêm filter logic và policy enum.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** đặt ngày nghỉ và policy xử lý khi tick miss
> **Để** schedule không chạy ngày lễ và không "dồn cục" sau outage

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cho phép đính kèm `skip_dates: [date]` (list ngày ISO) vào schedule — schedule KHÔNG tick trong các ngày này.
- Hệ thống PHẢI cho phép đính kèm `skip_windows: [{start_time, end_time, days_of_week}]` cho khoảng giờ trong tuần.
- Hệ thống PHẢI cung cấp `misfire_policy` enum: `catch_up` (chạy tick miss), `skip` (bỏ qua), `latest_only` (chỉ chạy tick miss gần nhất). Default `skip`.
- Hệ thống PHẢI áp dụng misfire policy khi workflow phục hồi sau gap > 1 tick interval.
- Hệ thống PHẢI ghi schedule_run với `trigger_source` ban đầu + flag `was_catch_up=true` nếu là catch-up tick.
- Hệ thống PHẢI validate skip_dates format ISO 8601, max 365 ngày forward.
- Hệ thống PHẢI cho phép PATCH skip_dates + misfire_policy mà không phải tạo schedule mới.
- Hệ thống PHẢI cho phép xem next_trigger_at đã tính trừ skip_dates.
- Hệ thống PHẢI emit metric `schedule.tick.skipped_due_to_calendar` để Operator audit.
- Hệ thống PHẢI từ chối skip_window có start > end (trừ khi cross-midnight được khai báo rõ).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Skip date — không tick vào ngày bỏ qua**

```
Given schedule S cron="0 8 * * *" skip_dates=["2026-12-25", "2026-01-01"]
When đến 2026-12-25 08:00
Then KHÔNG có schedule_run tạo
And metric schedule.tick.skipped_due_to_calendar +1
And next_trigger_at = 2026-12-26 08:00
```

**AC-2: Skip window — không tick trong khoảng giờ**

```
Given schedule S cron="0 * * * *" skip_windows=[{start:"02:00",end:"04:00",days:[*]}]
When đến 02:00, 03:00
Then KHÔNG tick
When đến 04:00
Then tick bình thường
```

**AC-3: Misfire policy=skip — bỏ tick miss**

```
Given schedule S cron="*/5 * * * *" misfire_policy="skip"
And farm down từ 12:00 đến 12:30
When farm up lúc 12:30
Then KHÔNG có schedule_run nào catch-up cho 12:05, 12:10, ..., 12:25
And tick kế tiếp = 12:35 (theo cron bình thường)
```

**AC-4: Misfire policy=latest_only — chạy tick miss gần nhất**

```
Given misfire_policy="latest_only"
And farm down 12:00 → 12:30, cron `*/5 * * * *`
When farm up
Then schedule_run cho tick gần nhất (12:25) được tạo với was_catch_up=true
And tick 12:05, 12:10, ..., 12:20 KHÔNG được tạo
And tick kế tiếp = 12:35
```

**AC-5: Misfire policy=catch_up — chạy tất cả tick miss**

```
Given misfire_policy="catch_up", cron `*/5 * * * *`
And farm down 12:00 → 12:30
When farm up
Then 6 schedule_run được tạo (12:00, 12:05, ..., 12:25) với was_catch_up=true
And tất cả dispatch trong < 60s sau khi farm up
```

**AC-6: Skip date overlap với tick miss + catch_up**

```
Given misfire_policy="catch_up" skip_dates=["2026-12-25"]
And farm down 2026-12-24 22:00 → 2026-12-25 02:00, cron `0 * * * *`
When farm up lúc 2026-12-25 02:00
Then tick 2026-12-24 22:00, 23:00 catch-up (trước skip date)
And tick 2026-12-25 00:00, 01:00 KHÔNG catch-up (trong skip date)
And next tick = 2026-12-26 00:00
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm holiday calendar global cho tổ chức — chỉ per-schedule skip_dates ở ticket này.
- KHÔNG bao gồm timezone per-schedule (vẫn UTC default) — lộ trình đặc tả module mục 7.
- KHÔNG bao gồm conditional skip-if (vd "skip nếu campaign trước chưa xong") — lộ trình đặc tả module mục 8.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `scheduling.calendar` filter logic skip_dates + skip_windows.
- [ ] Misfire policy enum + handler tại workflow restart.
- [ ] next_trigger_at compute trừ skip rules.

**Contract / API** (`layer:contract`)

- [ ] PATCH/POST schedule chấp nhận `skip_dates`, `skip_windows`, `misfire_policy`.
- [ ] GET schedule trả về 3 trường đó.

**Database / Migration** (`layer:db`)

- [ ] Cột `skip_dates JSONB DEFAULT '[]'`.
- [ ] Cột `skip_windows JSONB DEFAULT '[]'`.
- [ ] Cột `misfire_policy ENUM('catch_up','skip','latest_only') DEFAULT 'skip'`.
- [ ] Cột `was_catch_up BOOL DEFAULT false` trên schedule_runs (chuẩn bị DF-T-05-010).

**Documentation** (`layer:docs`)

- [ ] Doc 3 misfire policy với ví dụ.
- [ ] Doc skip_dates / skip_windows format.

**Test** (`layer:test`)

- [ ] Unit test 3 policy.
- [ ] Integration test farm down → restart with catch_up vs skip.
- [ ] Edge: skip_date overlap với catch-up window.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-05-004-01 | Positive | skip_dates ["2026-12-25"] | Wait Dec 25 08:00 | Không tick, metric skipped +1 |
| TC-DF-T-05-004-02 | Positive | misfire=skip, farm down 30m | Restart | Không catch-up |
| TC-DF-T-05-004-03 | Positive | misfire=latest_only, farm down 30m, cron */5 | Restart | 1 catch-up tick mới nhất |
| TC-DF-T-05-004-04 | Positive | misfire=catch_up, farm down 30m, cron */5 | Restart | 6 catch-up ticks |
| TC-DF-T-05-004-05 | Negative | skip_window start=10:00 end=08:00 không cross-midnight flag | POST | 400 INVALID_SKIP_WINDOW |
| TC-DF-T-05-004-06 | Negative | skip_dates > 365 ngày forward | POST | 400 SKIP_DATES_TOO_FAR |
| TC-DF-T-05-004-07 | Edge | catch_up + skip_date overlap | Restart cross-day | Catch-up trước skip date, dừng ở skip date |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-05-002 (workflow), DF-T-05-001 (entity).

**Chặn:** không (nice-to-have).

**Phụ thuộc giữa Epic:** không.

**Rủi ro:**

- **Catch-up dồn cục:** sau outage dài, catch_up tạo hàng trăm dispatch cùng lúc → quá tải. Giảm thiểu: limit max catch-up = 50; nếu vượt, downgrade sang `latest_only` và log warning.
- **DST / timezone confusion:** đặc tả module gap — timezone chưa giải quyết. Ticket này dùng UTC, doc ghi rõ.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] TC mapped.
- [ ] Doc 3 misfire policy với ví dụ test thật.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — FR-05-08 (workflow durable), mục 8 gap timezone.
- **Thuật ngữ:** Misfire policy, Catch-up, Skip date.
- **Nhóm người dùng:** Operator.
