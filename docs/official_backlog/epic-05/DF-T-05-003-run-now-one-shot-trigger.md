# DF-T-05-003 — Run-now & one-shot trigger

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-003 |
| **Title** | Run-now không đợi tick + one-shot schedule (no cron) |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Scheduling |
| **Priority** | P0 |
| **Story Points** | 3 |
| **Status** | `Backlog` |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-05-06 |
| **Truy vết — UC refs** | UC-05-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module UC-05-05 + FR-05-06: Operator cần trigger schedule **ngay lập tức**, ngoài lịch tick định kỳ (ví dụ vừa tạo schedule cron `0 8 * * *` xong, muốn test ngay luôn thay vì đợi đến 8h sáng mai). Đây là feature trải nghiệm rất rõ — Operator nhấn nút "Run now" và thấy campaign chạy ngay.

Ngoài run-now (kích trigger schedule có cron sẵn), ticket này thêm **one-shot schedule** — schedule chạy một lần tại thời điểm cụ thể (vd "chạy lúc 2026-05-30 14:00 UTC") rồi tự deactivate. Khác với cron schedule (lặp), one-shot không cần cron expression — chỉ cần `run_at` timestamp.

P0 vì là feature Operator dùng hằng ngày trong giai đoạn rollout scenario. SP 3 vì re-dùng infrastructure của DF-T-05-002 (dispatch tới Campaign, ghi schedule_run history) — chỉ thêm hai trigger source mới: `run_now` và `one_shot`.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** trigger schedule chạy ngay không cần đợi tick cron, hoặc tạo schedule chạy 1 lần tại thời điểm xác định
> **Để** test schedule mới ngay sau khi cấu hình, hoặc chạy campaign cho event one-time

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp endpoint `POST /schedules/{id}/run-now` để trigger schedule ngay — trace FR-05-06.
- Hệ thống PHẢI tạo schedule_run với `trigger_source="run_now"` để phân biệt với tick định kỳ.
- Hệ thống PHẢI KHÔNG thay đổi lịch tick định kỳ khi run-now (cron vẫn tick bình thường vào giờ kế tiếp).
- Hệ thống PHẢI hỗ trợ tạo one-shot schedule với `run_at` timestamp thay cho `cron_expression`.
- Hệ thống PHẢI tự chuyển one-shot sang `disabled` sau khi đã chạy xong (terminal one-shot).
- Hệ thống PHẢI từ chối run-now nếu schedule đang `disabled` hoặc `deleted` (operator phải bật trước).
- Hệ thống PHẢI từ chối tạo schedule với cả `cron_expression` lẫn `run_at` (mutually exclusive).
- Hệ thống PHẢI validate `run_at` > now + 1 phút (không cho phép quá khứ).
- Hệ thống PHẢI cho phép cancel one-shot schedule trước khi `run_at` đến (toggle off).
- Hệ thống PHẢI emit metric `schedule.run_now.count` để track tần suất Operator dùng.
- Hệ thống PHẢI yêu cầu permission `schedule.run-now` riêng (có thể tách khỏi `schedule.update`).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Run-now schedule cron — không phá lịch định kỳ**

```
Given schedule S cron="0 8 * * *" enabled, đang là 14:30
When POST /schedules/S/run-now
Then 202 Accepted, schedule_run mới với trigger_source="run_now", created_at=14:30
And dispatch campaign target được gọi
And tick định kỳ vẫn chạy đúng 08:00 sáng hôm sau (không bị reset)
```

**AC-2: One-shot schedule — tự deactivate sau khi chạy**

```
Given POST schedule { run_at: "2026-05-30T14:00:00Z", target_campaign: C }
When đến 14:00:00
Then schedule_run trigger_source="one_shot" tạo, campaign dispatch
And sau khi run xong, schedule.status="disabled" tự động (không trigger lại)
```

**AC-3: Run-now schedule disabled — reject**

```
Given schedule S status="disabled"
When POST /schedules/S/run-now
Then 409 "SCHEDULE_DISABLED" với hướng dẫn "bật trước khi run-now"
```

**AC-4: One-shot với run_at quá khứ — reject**

```
Given hiện tại là 2026-05-26T10:00:00Z
When POST schedule { run_at: "2026-05-25T10:00:00Z" }
Then 400 "RUN_AT_IN_PAST"
```

**AC-5: Mutually exclusive cron và run_at**

```
Given user POST { cron_expression: "0 8 * * *", run_at: "2026-05-30T14:00:00Z" }
When validate
Then 400 "CRON_AND_RUN_AT_MUTUALLY_EXCLUSIVE"
```

**AC-6: Run-now trong khi schedule đang trong tick cron**

```
Given schedule S vừa tick cron lúc 14:00, schedule_run R1 đang chạy
When POST /schedules/S/run-now lúc 14:01
Then schedule_run R2 mới được tạo, source="run_now", song song với R1
And module Campaign nhận 2 dispatch độc lập (xử lý ở mức của nó)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm rate limit run-now per user — DF-T-05-008 quota.
- KHÔNG bao gồm UI nút run-now — DF-E-11.
- KHÔNG bao gồm batch run-now (nhiều schedule cùng lúc) — gom vào DF-T-05-011 bulk operation.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Service method `run_schedule_now(schedule_id, user_id)`.
- [ ] Validation logic mutually exclusive cron/run_at.
- [ ] One-shot deactivate logic sau khi terminal.
- [ ] Permission check `schedule.run-now`.

**Contract / API** (`layer:contract`)

- [ ] Endpoint `POST /schedules/{id}/run-now` → 202 + schedule_run_id.
- [ ] Endpoint `POST /schedules` mở rộng accept `run_at` (alt cron).
- [ ] Mã lỗis: `SCHEDULE_DISABLED`, `RUN_AT_IN_PAST`, `CRON_AND_RUN_AT_MUTUALLY_EXCLUSIVE`.

**Database / Migration** (`layer:db`)

- [ ] Cột `run_at TIMESTAMP NULL` trên `schedules`.
- [ ] Constraint check: `(cron_expression IS NOT NULL) XOR (run_at IS NOT NULL)`.

**Documentation** (`layer:docs`)

- [ ] Doc khác biệt cron schedule vs one-shot schedule.
- [ ] Ví dụ run-now trong API doc.

**Test** (`layer:test`)

- [ ] Unit test run-now + one-shot.
- [ ] Test cron không bị reset khi run-now.
- [ ] Test one-shot self-deactivate.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-05-003-01 | Positive | Schedule S enabled cron | POST /S/run-now | 202, schedule_run source="run_now", cron tick định kỳ không đổi |
| TC-DF-T-05-003-02 | Positive | One-shot run_at=future | Chờ tới run_at | Schedule_run source="one_shot", schedule tự disabled sau khi terminal |
| TC-DF-T-05-003-03 | Negative | Schedule disabled | POST run-now | 409 SCHEDULE_DISABLED |
| TC-DF-T-05-003-04 | Negative | run_at quá khứ | POST schedule | 400 RUN_AT_IN_PAST |
| TC-DF-T-05-003-05 | Negative | Cả cron và run_at | POST schedule | 400 CRON_AND_RUN_AT_MUTUALLY_EXCLUSIVE |
| TC-DF-T-05-003-06 | Edge | Run-now lúc tick cron đang chạy | POST đồng thời với tick | 2 schedule_run riêng, không dedup |
| TC-DF-T-05-003-07 | Edge | One-shot toggle off trước run_at | Toggle off lúc run_at-5m | Tick không chạy, schedule disabled |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-05-001, DF-T-05-002.

**Chặn:** DF-T-05-010 (history record cần phân biệt trigger source).

**Phụ thuộc giữa Epic:** DF-E-04 dispatch endpoint.

**Rủi ro:**

- **Run-now spam:** Operator click nhanh nhiều lần → nhiều dispatch — sẽ giải bằng quota DF-T-05-008. Tạm thời rate-limit ở reverse proxy 5 req/s per user.
- **One-shot miss khi farm down tại run_at:** dùng Temporal workflow cho one-shot (re-dùng infrastructure DF-T-05-002) — workflow durable sẽ catch-up.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] TC mapped.
- [ ] Run-now metric exposed.
- [ ] Doc one-shot vs cron phân biệt rõ.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — FR-05-06, UC-05-05.
- **Thuật ngữ:** Run-now, Schedule run, One-shot.
- **Nhóm người dùng:** Operator, Automation Builder.
