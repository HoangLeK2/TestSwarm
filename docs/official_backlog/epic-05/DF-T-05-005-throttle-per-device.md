# DF-T-05-005 — Throttle per device (capacity planning)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-005 |
| **Title** | Throttle per device — giới hạn concurrent schedule run trên mỗi thiết bị |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Scheduling |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:contract`, `type:feature`, `risk:performance`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-05-01 (mở rộng capacity planning), gap mục 8 concurrency |
| **Truy vết — UC refs** | UC-05-09 (operator biết được trùng giờ chạy chồng) |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 8 cảnh báo rõ: hiện chưa có concurrency lock — hai schedule cùng giờ và cùng nhắm device sẽ chạy chồng, tranh chấp device runtime. Lộ trình mục 2.4 đặt "Concurrency lock schedule" ở mức P2 trung hạn. Ticket này là bước đầu — không phải lock cứng, mà là **soft throttle**: mỗi device có giới hạn `max_concurrent_executions` (mặc định 1); khi schedule tick mà device đang busy, schedule_run được hoãn vào queue thay vì dispatch ngay (hoặc bị reject tùy policy).

Đối tượng chính là Fleet Operator: muốn tránh việc 5 campaign nhắm cùng 100 device cùng giờ, gây race UI. Đối tượng phụ là Social Data Operator: hiểu được lý do tại sao schedule_run đôi khi bị `deferred` hoặc `throttled`.

P1 vì ảnh hưởng KPI đặc tả module "Số sự cố schedule trùng giờ gây tranh chấp device < 1/quý/org". SP 5 vì có 2 mode (defer vs reject), tích hợp với module Devices (DF-E-02) để đọc capacity per device.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** giới hạn số schedule_run đồng thời trên mỗi device
> **Để** tránh tranh chấp UI, race condition, và đảm bảo throughput ổn định

Persona phụ: Social Data Operator (xem rõ lý do schedule_run bị defer).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cho phép cấu hình `max_concurrent_per_device` ở 2 cấp: organization default (vd 1), per-device override.
- Hệ thống PHẢI kiểm tra capacity device trước khi dispatch schedule_run.
- Hệ thống PHẢI hỗ trợ 2 mode khi device busy: `defer` (xếp hàng đợi tối đa N phút), `reject` (mark schedule_run status="throttled_rejected").
- Hệ thống PHẢI emit metric `schedule.run.throttled{mode}` để track tần suất.
- Hệ thống PHẢI ghi schedule_run lý do throttle: `device_id`, `reason="device_at_capacity"`, `deferred_until`.
- Hệ thống PHẢI auto-dispatch khi device free (cho mode defer) trong deferred_window.
- Hệ thống PHẢI hủy schedule_run trong queue khi vượt deferred_window (vd 10 phút) — chuyển sang `throttled_expired`.
- Hệ thống PHẢI từ chối tạo schedule với `max_concurrent_per_device > device.capacity` (validation hard cap).
- Hệ thống PHẢI emit event `schedule.run.throttled` cho notification (DF-E-09).
- Hệ thống PHẢI cho phép override per-schedule: schedule mang ý nghĩa SLA cao có thể bypass throttle với flag `priority=high` (cần permission đặc biệt).
- Hệ thống PHẢI track "current concurrent" count per device chính xác qua Redis counter (atomic INCR/DECR).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Throttle mode=defer — chờ device free**

```
Given device D max_concurrent=1, đang chạy execution E1
And schedule S nhắm device D tick lúc 12:00
When tick xảy ra
Then schedule_run R tạo với status="deferred", deferred_until=12:10
And khi E1 xong lúc 12:05, R tự dispatch
And schedule_run R thành công, total deferred 5 phút
```

**AC-2: Throttle mode=reject — không xếp hàng**

```
Given device D max_concurrent=1, busy
And schedule S throttle_mode="reject"
When tick
Then schedule_run R status="throttled_rejected" lý do "device_at_capacity"
And KHÔNG queue, KHÔNG dispatch sau đó
And event schedule.run.throttled phát
```

**AC-3: Deferred expired**

```
Given schedule_run R status="deferred", deferred_until=12:10
And device D vẫn busy đến 12:11
When 12:10 timeout
Then R chuyển sang "throttled_expired", lý do "deferred_window_exceeded"
And event phát cho notification
```

**AC-4: Bypass với priority=high**

```
Given device D busy, schedule S priority="high" với permission schedule.high-priority
When tick
Then schedule_run R dispatch ngay (không throttle)
And device D có 2 concurrent execution (vượt max=1) — log warning
And metric schedule.priority_bypass +1
```

**AC-5: Validate max_concurrent > device capacity — reject**

```
Given device D capacity=2 (declared by fleet)
When POST schedule { max_concurrent_per_device: 5 }
Then 400 "EXCEEDS_DEVICE_CAPACITY"
```

**AC-6: Race condition — 2 tick cùng phút**

```
Given device D max_concurrent=1, idle
And schedule S1, S2 cùng tick lúc 12:00 nhắm D
When 2 dispatch song song
Then chỉ 1 schedule_run được dispatch (atomic INCR thắng)
And cái kia status="deferred" hoặc "throttled_rejected" theo mode
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm throttle per account — DF-T-05-006.
- KHÔNG bao gồm fairness/anti-starvation — DF-T-05-007.
- KHÔNG bao gồm device capacity declaration — đã có trong DF-E-02.
- KHÔNG bao gồm UI hiển thị "deferred queue" — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `scheduling.throttle.device` với Redis counter atomic.
- [ ] Defer queue (Redis sorted set keyed by `deferred_until`).
- [ ] Background worker dequeue khi device free.
- [ ] Permission check `schedule.high-priority`.

**Contract / API** (`layer:contract`)

- [ ] Schedule POST/PATCH chấp nhận `throttle_mode`, `priority`, `max_concurrent_per_device`.
- [ ] Schedule_run response thêm `throttle_status`, `deferred_until`.
- [ ] Mã lỗis: `EXCEEDS_DEVICE_CAPACITY`, `DEVICE_AT_CAPACITY`.

**Database / Migration** (`layer:db`)

- [ ] Cột `throttle_mode ENUM('defer','reject') DEFAULT 'defer'` trên schedules.
- [ ] Cột `priority ENUM('normal','high') DEFAULT 'normal'`.
- [ ] Cột `max_concurrent_per_device INT DEFAULT 1`.
- [ ] Cột `throttle_status`, `deferred_until` trên schedule_runs.

**Infra / DevOps** (`layer:infra`)

- [ ] Redis keys: `device:{id}:concurrent_count`, `device:{id}:defer_queue`.
- [ ] Metric `schedule_run_throttled_total{mode,reason}`.

**Documentation** (`layer:docs`)

- [ ] Doc capacity planning cho Fleet Operator.
- [ ] Doc tradeoff defer vs reject.

**Test** (`layer:test`)

- [ ] Unit test throttle logic.
- [ ] Race test 2 schedule cùng tick.
- [ ] Integration test deferred → device free → auto-dispatch.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-05-005-01 | Positive | Device D busy, schedule defer mode | Tick | Schedule_run deferred, auto-dispatch khi D free |
| TC-DF-T-05-005-02 | Positive | Device D busy, schedule reject mode | Tick | Schedule_run throttled_rejected, event phát |
| TC-DF-T-05-005-03 | Positive | Schedule priority=high, device busy | Tick | Bypass throttle, log warning |
| TC-DF-T-05-005-04 | Negative | max_concurrent=5 > device capacity 2 | POST schedule | 400 EXCEEDS_DEVICE_CAPACITY |
| TC-DF-T-05-005-05 | Negative | Priority=high không có permission | POST schedule | 403 INSUFFICIENT_PERMISSION |
| TC-DF-T-05-005-06 | Edge | 2 schedule cùng tick race | Inject concurrent | Chỉ 1 dispatch, atomic counter chính xác |
| TC-DF-T-05-005-07 | Edge | Deferred 10 phút không free | Wait timeout | throttled_expired |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-05-002 (workflow), DF-E-02 (device entity + capacity).

**Chặn:** DF-T-05-007 (fairness cần throttle layer).

**Phụ thuộc giữa Epic:** DF-E-02 cung cấp `device.capacity` field.

**Rủi ro:**

- **Redis lệch counter:** crash giữa INCR và DECR → counter stuck. Giảm thiểu: TTL counter = 2× max execution duration, reset hàng đêm.
- **Defer queue size:** 10k schedule cùng defer → Redis sorted set grow. Limit max queue per device = 100.
- **Priority abuse:** Operator lạm dụng high-priority → audit log mọi bypass, alert nếu > 10%/ngày.

**Phụ thuộc bên ngoài:** Redis 6+.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] TC mapped.
- [ ] Load test 100 schedule cùng tick: throttle hoạt động đúng.
- [ ] Metric exposed trong Grafana.
- [ ] Audit log priority bypass.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — mục 8 concurrency gap, UC-05-09.
- **Thuật ngữ:** Throttle, Defer, Schedule run.
- **Nhóm người dùng:** Fleet Operator, Social Data Operator.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — Concurrency lock schedule.
