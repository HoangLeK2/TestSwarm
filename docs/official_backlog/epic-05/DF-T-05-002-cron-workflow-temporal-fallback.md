# DF-T-05-002 — Cron schedule workflow durable + fallback dispatcher

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-05-002 |
| **Title** | Cron schedule workflow durable trên Temporal + fallback dispatcher khi Temporal off |
| **Type** | `type:feature` |
| **Epic** | DF-E-05 — Scheduling |
| **Module** | DF-MOD-05 — Scheduling |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | `Done` |
| **Labels** | `module:scheduling`, `layer:backend`, `layer:infra`, `type:feature`, `risk:data-loss`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-05-01, FR-05-02, FR-05-08, FR-05-09 |
| **Truy vết — UC refs** | UC-05-01, UC-05-07, UC-05-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Sau khi schedule entity sẵn sàng (DF-T-05-001), cần engine **trigger tick theo cron**. Đặc tả module mục 5.1 mô tả vòng đời từ tạo tới tick, mục 5.3 mô tả chế độ fallback khi Temporal không sẵn sàng. Ticket này build engine đó — đây là core runtime của toàn DF-E-05.

Bài toán nghiệp vụ: Operator đặt schedule "0 8 * * *" rồi không quan tâm nữa; hệ thống chịu trách nhiệm tick đúng 8h sáng mỗi ngày. Khi Temporal ổn định → schedule workflow durable đảm bảo không miss tick dù farm restart. Khi Temporal tạm tắt (upgrade, sự cố) → fallback dispatcher đảm bảo tick vẫn được trigger ở mức best-effort, KHÔNG để schedule "im lặng chết".

P0 vì block DF-T-05-003, DF-T-05-004, DF-T-05-005, DF-T-05-006, DF-T-05-009, DF-T-05-010. SP 5 vì Temporal workflow đã có pattern trong DF-E-04 — chỉ thêm cron parsing và fallback đường thứ hai. **Risk data-loss**: nếu engine miss tick âm thầm, Operator không biết, mất audit — phải có metric + banner cảnh báo.

Validate cron expression ở backend chính thức được implement ở ticket này (DF-T-05-001 chỉ basic syntax check); FE parser được validate chéo trong DF-T-11-* (DF-E-11), nhưng contract về mã lỗi cần đặt ở đây.

## 3. Câu chuyện người dùng

> **Là** Operator
> **Tôi muốn** schedule tự trigger campaign đúng giờ theo cron mỗi ngày, kể cả khi Temporal tạm thời không sẵn sàng
> **Để** không miss giờ vàng vận hành và không cần check thủ công

Persona phụ: Automation Builder (cần biết tick có chạy không trong giai đoạn rollout); Platform Engineer (monitor fallback mode).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI khởi tạo schedule workflow trên Temporal khi schedule chuyển sang `enabled` lần đầu — trace FR-05-08.
- Hệ thống PHẢI parse cron expression đầy đủ (5 trường standard UNIX cron, hỗ trợ `*`, `,`, `-`, `/`) với cùng library FE/BE; cấm `@reboot` và `?` để tránh ambiguity.
- Hệ thống PHẢI tick đúng giờ với độ lệch p99 < 30 giây khi chạy qua Temporal — trace KPI đặc tả module.
- Hệ thống PHẢI tự chuyển sang fallback dispatcher khi Temporal không health-check trong > 60 giây — trace FR-05-09.
- Hệ thống PHẢI hiển thị banner cảnh báo trên dashboard khi đang ở fallback mode (FE tiêu thụ trong DF-E-11; BE expose flag).
- Hệ thống PHẢI emit metric `schedule.tick.source` với label `temporal|fallback` để observability.
- Hệ thống PHẢI dừng workflow khi schedule chuyển sang `disabled` hoặc `deleted`; resume khi `enabled` lại.
- Hệ thống PHẢI handle case Temporal sống lại sau fallback — workflow mới được khởi tạo, không chạy double tick cùng phút.
- Hệ thống PHẢI validate cron expression đồng nhất giữa FE/BE với cùng mã lỗi `INVALID_CRON_EXPRESSION` — trace FR-05-02.
- Hệ thống PHẢI cập nhật `schedule.next_trigger_at` mỗi khi cron parse hoặc tick xong.
- Hệ thống PHẢI persist tick history dù chạy ở Temporal hay fallback (delegate sang DF-T-05-010 cho schedule_run record).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tick định kỳ qua Temporal — luồng thành công**

```
Given Temporal up, schedule S cron="*/5 * * * *" enabled
When đến phút chia hết 5 (vd 12:05:00)
Then schedule workflow tick trong khoảng 12:05:00 → 12:05:30 (lệch < 30s)
And schedule_run mới được tạo trigger_source="temporal"
And dispatch campaign target được gọi với schedule_run_id reference
```

**AC-2: Fallback khi Temporal off — không miss tick**

```
Given Temporal down (health-check fail > 60s)
And schedule S cron="*/5 * * * *" enabled
When đến tick
Then fallback dispatcher trigger schedule_run với trigger_source="fallback"
And banner "Fallback mode active" hiển thị qua API /system/schedule-status
And metric schedule.tick.source{source="fallback"} +1
```

**AC-3: Temporal phục hồi sau fallback — không double tick**

```
Given fallback đang chạy, schedule S vừa tick lúc 12:05 trong fallback
When Temporal up trở lại lúc 12:07
Then schedule workflow Temporal khởi tạo lại với cursor = 12:10 (tick kế tiếp)
And KHÔNG có schedule_run trùng phút 12:05
```

**AC-4: Cron expression không hợp lệ — reject với mã lỗi chuẩn**

```
Given user PATCH cron="bad * cron"
When backend validate
Then 400 "INVALID_CRON_EXPRESSION" message chỉ vị trí field sai
And response giống hệt format FE validator để DF-E-11 share error message
```

**AC-5: Disable schedule trong khi workflow đang chạy**

```
Given schedule S workflow Temporal active
When toggle S → disabled
Then workflow Temporal nhận signal cancel trong < 5 giây
And tick kế tiếp KHÔNG chạy
And không có schedule_run nào được tạo sau toggle
```

**AC-6: Edge case — Temporal restart đúng lúc tick**

```
Given Temporal restart bắt đầu lúc 12:04:55
And schedule S tick lúc 12:05:00
When workflow Temporal khôi phục sau 10 giây
Then schedule_run lúc 12:05 vẫn được tạo (workflow durable đảm bảo)
And trigger source vẫn là "temporal" (không phải fallback)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm schedule CRUD — DF-T-05-001.
- KHÔNG bao gồm run-now — DF-T-05-003.
- KHÔNG bao gồm conflict detection — DF-T-05-009.
- KHÔNG bao gồm UI banner fallback — sẽ tiêu thụ ở DF-E-11.
- KHÔNG bao gồm throttle/quota check trước khi tick — DF-T-05-005, DF-T-05-006, DF-T-05-008.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `scheduling.workflows` Temporal workflow với cron timer.
- [ ] Module `scheduling.fallback` poll-based dispatcher (poll mỗi 10s `schedules` có next_trigger_at <= now).
- [ ] Health-check Temporal + auto-switch giữa hai mode.
- [ ] Cron parser shared utility (Python + TS — cùng spec).
- [ ] Lock dedup khi double tick (Redis SETNX với key `schedule:{id}:tick:{epoch_minute}`).

**Contract / API** (`layer:contract`)

- [ ] Endpoint `GET /system/schedule-status` trả `{ mode: "temporal" | "fallback", temporal_healthy: bool }`.
- [ ] Mã lỗi `INVALID_CRON_EXPRESSION` với schema chuẩn.

**Database / Migration** (`layer:db`)

- [ ] Index `schedules(next_trigger_at)` partial WHERE status='enabled' cho fallback poll.
- [ ] Cột `trigger_source ENUM('temporal','fallback')` trong schedule_runs (chuẩn bị cho DF-T-05-010).

**Infra / DevOps** (`layer:infra`)

- [ ] Temporal namespace `df-scheduling`.
- [ ] Prometheus metric: `schedule_tick_total{source}`, `schedule_tick_drift_seconds`.
- [ ] Alert: `temporal_healthy==0` > 5 phút.

**Documentation** (`layer:docs`)

- [ ] Doc cron syntax được hỗ trợ + ví dụ + ký tự bị cấm.
- [ ] Runbook: "Temporal off — kiểm tra fallback đang chạy".

**Test** (`layer:test`)

- [ ] Unit test cron parser FE/BE chéo.
- [ ] Integration test: kill Temporal → fallback tick.
- [ ] Chaos test: restart Temporal trong lúc tick.
- [ ] Dedup test: double tick cùng phút chỉ tạo 1 schedule_run.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-05-002-01 | Positive | Temporal up, cron `*/5 * * * *` | Chờ tick | Tick trong < 30s lệch, schedule_run trigger_source="temporal" |
| TC-DF-T-05-002-02 | Positive | Temporal off > 60s, cron `*/5 * * * *` | Chờ tick | Fallback tick trong < 90s lệch, trigger_source="fallback", banner active |
| TC-DF-T-05-002-03 | Positive | Temporal restart 10s trong lúc tick | Chờ workflow phục hồi | Tick được trigger sau restart, không miss |
| TC-DF-T-05-002-04 | Negative | Cron `@reboot` | POST schedule | 400 INVALID_CRON_EXPRESSION |
| TC-DF-T-05-002-05 | Negative | Cron `bad cron` | PATCH schedule | 400 INVALID_CRON_EXPRESSION với position |
| TC-DF-T-05-002-06 | Negative | Schedule disabled trong workflow đang chạy | Toggle off → đợi tick | Tick KHÔNG được trigger |
| TC-DF-T-05-002-07 | Edge | Fallback + Temporal cùng tick một phút | Inject race | Dedup lock → chỉ 1 schedule_run được tạo |
| TC-DF-T-05-002-08 | Edge | 1000 schedule cùng tick `0 8 * * *` | Wait 8:00 | Tất cả tick trong < 90s, không lost |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-05-001 (schedule entity).

**Chặn:** DF-T-05-003, DF-T-05-004, DF-T-05-005, DF-T-05-006, DF-T-05-009, DF-T-05-010.

**Phụ thuộc giữa Epic:** DF-E-04 — Temporal namespace shared với execution workflow; phải đảm bảo không xung đột task queue.

**Rủi ro:**

- **Double tick:** Temporal + fallback cùng trigger → dedup qua Redis lock theo `{schedule_id, epoch_minute}`.
- **Drift parser FE/BE:** đặc tả module mục 8 cảnh báo → ticket này chốt cùng library `croniter` (Python) và `cron-parser` (TS), kèm bộ test chéo 200+ cron expressions.
- **Fallback poll quá tải:** 10s × 10k schedule → DB hot — đảm bảo có index partial trên next_trigger_at.
- **Silent miss:** không tick mà không alert → metric drift + alert > 90s drift trên Temporal mode.

**Phụ thuộc bên ngoài:** Temporal SDK; `croniter` library; Redis cho dedup lock.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Tất cả TC mapped sang automation.
- [ ] Cron parser FE/BE chạy chung test fixture 200+ expressions.
- [ ] Chaos test: kill Temporal 10 phút, không miss tick (qua fallback) — pass.
- [ ] Metric `schedule_tick_drift_seconds` p99 < 30s trên Temporal, < 90s trên fallback (staging).
- [ ] Runbook fallback published.
- [ ] Code review ≥ 1 approve từ owner module + owner Temporal infra.
- [ ] Release notes ghi rõ fallback mode contract.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [05-scheduling.md](../../official_docs/modules/05-scheduling.md) — mục 5.3, FR-05-02, FR-05-08, FR-05-09.
- **Thuật ngữ:** Cron expression, Schedule, Temporal, Workflow.
- **Nhóm người dùng:** Operator, Platform Engineer.
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — Concurrency lock schedule (P2 trung hạn).
