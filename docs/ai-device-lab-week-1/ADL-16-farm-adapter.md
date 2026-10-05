# ADL-16 — Farm adapter production: durable delivery và correlation

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / IMPLEMENTATION_COMPLETE — PASS_APPROVED_EMULATOR — PENDING_INDEPENDENT_REVIEW |
| Owner / review | BE runtime / distributed-systems reviewer + security + QA |
| Dependencies | 01, 04, 18a; reservation 05; secret resolution 18b trước credential job |
| Deliverable | Job/event schema, outbox/inbox adapter, replay/cancel tests, live correlation proof |

## 2. Source/gap
`backend/services/campaign_dispatch.py`, `backend/services/scheduler.py`, execution/event models có correlation/idempotency; thiếu service attempt/job interface. `ExecutionStep` retry step khác RunAttempt. Tái sử dụng dispatcher, không tạo runner riêng bypass policy.

## 3. Contract
| Payload | Required |
|---|---|
| Job | schema_version, org/campaign/lane/slot/run_attempt, device_id/reservation_id, observed/target build ref, approved scenario version/hash/policy, deadline, allowed operations/package, idempotency key, optional secret reference |
| Event | event_id/source/sequence nếu source hỗ trợ, occurred_at/received_at, job/execution IDs, step path/index, step attempt index, state/verdict/reason, artifact refs; no bytes/secrets |

Transaction commit writes intent/outbox cùng RunAttempt; delivery at-least-once với consumer dedup, **không hứa exactly-once external side effect** nếu relay không bảo đảm. Ambiguous tap/command timeout không auto-repeat unsafe action; block/reconcile. Unique job key và evidence-based terminal reducer không đảo cancelled/blocked thành passed do late event; completion dùng assertion data, không arrival order.

## 4. Bước làm
1. Sign job/event schema và state/reducer rules, supported engine matrix và payload limits.
2. Implement transactional outbox + delivery/retry lease + durable event inbox/dedup; version unknown reject rõ.
3. Dispatcher checks reservation/health/approval/policy then claim; execute in existing Temporal/fallback path.
4. Cancel/deadline drain, release claim sau safe terminal confirmation; recovery stale job không chạy duplicate.
5. Operator job inspect trace; contract/fault tests và Approved Device Target identity chain proof.

## 5. Acceptance
- [x] AC1: trace slot→run attempt→job/execution→step retry→artifact đủ IDs.
- [x] AC2: crash/replay/delivery duplicate không tạo job mới ngoài policy.
- [x] AC3: out-of-order terminal events xử lý deterministic, no false pass.
- [x] AC4: cancellation/deadline/release/recovery có observation và audit.
- [x] AC5: payload bounded/no secret bytes, Temporal/fallback cùng dùng pinned snapshot, policy và terminal reducer.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 16-T1 | API run→Approved Device Target→persisted evidence | Identity chain exact, target type và version/hash pinned |
| 16-T2 | Crash sau DB commit trước delivery; resend key | One accepted job/attempt; outbox recovered |
| 16-T3 | Duplicate/reordered fail/cancel/complete events | Terminal rules preserved, no Blocked→Passed |
| 16-T4 | Relay command response lost sau tap | Reconcile/block uncertain side effect, no blind duplicate |
| 16-T5 | Deadline/cancel during run | Drain/release; no future commands after confirmed cancel |
| 16-T6 | Temporal/fallback supported engines | Same semantics; payload size/reference tests |

## 7. Review và DoD
Runtime reviewer signs delivery uncertainty/reducer, security payload/policy, QA fault injections, operator verifies Approved Device Target. Evidence target type, outbox/inbox rows, event replay trace, command IDs/timestamps, engine/version outputs. Fail → pause delivery/REWORK/rerun recovery. DONE needs AC1–5; credential jobs additionally 18b PASS, no dependency cycle in schema design.

## 8. Kết quả 04/10/2026

- Báo cáo: [`reports/ADL-16-emulator-farm-adapter-2026-10-04.md`](reports/ADL-16-emulator-farm-adapter-2026-10-04.md).
- Approved Device Target: Android emulator `emulator-5580`, `observed_device_count=1`, `capacity_waiver=WVR-12`.
- Chuỗi live fallback đã PASS: approved snapshot → transactional attempt/job/outbox → existing scenario executor → bốn persisted steps → terminal inbox/reducer → slot `completed/pass`.
- Temporal adapter và fallback adapter chạy cùng validation/reducer contract; cả hai đều theo dõi terminal result, chờ cancel drain và ghi cùng event reducer. Public API không thể tự ghi terminal pass.
- Event contract `adl-farm-event-v1` bắt buộc `execution_id`, giới hạn 2.000 event/job, 64 KiB/event và 1.024 bytes/artifact reference; reducer chỉ tải terminal evidence.
- Build cài thật được đọc bằng `dumpsys package` và so khớp `versionName/versionCode` trước dispatch. Local emulator dùng ADB scoped theo serial cho shell/app launch, tái sử dụng forward khỏe và dọn forward cũ.
- Regression hiện tại: 120 backend tests PASS, 1 skip; focused review suite 16 PASS; frontend typecheck PASS; Playwright 11 PASS. OpenAPI và generated TypeScript client đã đồng bộ.
- Independent distributed-systems/security/QA sign-off vẫn `PENDING_REVIEW`; không được suy diễn từ kiểm thử local.
