# ADL-07 — Lịch 168 slots, quota ledger và execution exceptions

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | BE scheduler + operator / DB/runtime + QA |
| Dependencies | 04, 06, 16; device reservation 05 và billing entitlement 09 |
| Deliverable | Slot materialization, dispatch/catch-up rules, quota ledger/API, 12-Approved-Device-Target day proof |

## 2. Source/gap
`backend/services/scheduler.py`, `backend/temporal/schedule_workflow.py`, Schedule/Run có cron/misfire/idempotency. Missing service-day identity/quota contract. Tái dùng scheduler trigger, nhưng unique slot thuộc service domain, không đếm từ ScheduleRun.

## 3. Contract
- Plan version lưu 12 lanes×14 service_days; unique 168 slots. Day windows là 14 khoảng 24h từ started_at; timezone dùng hiển thị/giờ dispatch. Nếu chọn calendar-day semantics thay 24h phải ADR và test DST trước code, không trộn hai định nghĩa.
- Slot state phân tách scheduled/due/claimed/running/terminal/missed; verdict pass/fail/inconclusive/blocked riêng. Retry không tăng scheduled_count.
- Quota ledger append-only unique charge key per attempt/resource segment: reserved/consumed/released/adjusted; đo actual device seconds, không dùng estimated 15 phút làm actual.
- 15 phút deadline/2.520 phút trần kế hoạch cần plan được owner duyệt. Run retries/extra retest cost và catch-up deadline/cap phải explicit; no unlimited retry.
- Default scenario policy core/explore/retest/finalize có version; không tự nói explore arbitrary app actions nếu ngoài approval.

## 4. Bước làm
1. Chốt day/slot/misfire/retry/quota policy với product, domain 04 và adapter 16.
2. Start intent materializes 168 rows transactionally/idempotently; scheduler lấy due slots, atomic claim/outbox và stale claim recovery.
3. Runtime outcome updates slot/attempt và quota ledger; deadline cancels/drains, releases claim/quota balance đúng.
4. API counts/history/reason, pause/cancel skip future due slots; không dispatch ngoài reservation.
5. Run clock/race/replay tests; staging one-day 12 Approved Device Targets độc lập rồi bàn giao 12 targets vận hành dài ngày.

## 5. Acceptance
- [ ] AC1: 168 unique slots, 12 mỗi service day; restart không thêm rows.
- [ ] AC2: replay/concurrent trigger không tạo duplicate attempts ngoài retry policy.
- [ ] AC3: quota ledger reconcile actual minutes/retry allocation và không âm.
- [ ] AC4: offline/timeout/missed/blocked outcomes rõ, không pass.
- [ ] AC5: một ngày 12 Approved Device Targets có identity/evidence đầy đủ; chronology 14 ngày chưa được đóng ở task này.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 07-T1 | Start twice + restart materializer | 168 rows, same slot IDs |
| 07-T2 | Crash after claim/outbox before ack, replay | One accepted job/attempt; stale claim recoverable |
| 07-T3 | Boundary UTC/timezone/DST with fixed clock | Service day 1..14 correct; không slot day 15 |
| 07-T4 | Deadline/offline/retry and ledger replay | Correct blocked/timeout; consumed/released reconciles |
| 07-T5 | Pause/cancel trước due và during active run | No future job; active drained, claim released |
| 07-T6 | 12 devices one-day run plus replacement | 12 lanes, không lane 13; DB/API/device target IDs khớp |

## 7. Review và DoD
Runtime reviewer kiểm replay/deadline, DB reviewer quota transaction, QA race/clock và operator Approved Device Target proof. Lưu ledger reconciliation, timestamps, slot IDs, commands, engine version và captures. Fail → REWORK; không xóa missed slots để đạt tỷ lệ. DONE cần AC1–5 và engine parity cho tất cả đường được support.
