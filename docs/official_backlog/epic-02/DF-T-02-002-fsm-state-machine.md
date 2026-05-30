# DF-T-02-002 — FSM state machine — định nghĩa và state store

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-002 |
| **Title** | FSM trạng thái thiết bị — định nghĩa, transition rule và state store ở control plane |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-02, FR-02-03, FR-02-13, FR-03-04 (cross-Epic) |
| **Truy vết — UC refs** | UC-02-02, UC-02-12, UC-03-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mô tả mỗi thiết bị Android có một máy trạng thái hữu hạn UNKNOWN → CONNECTING → ONLINE ↔ BUSY → RECONNECTING → DEAD. State machine này được duy trì cả ở agent (nguồn sự kiện) và ở control plane (nguồn truy vấn, hiển thị, ra quyết định dispatch). Nếu hai phía drift, fleet view sẽ sai và mọi quyết định nghiệp vụ phía trên (claim, dispatch, alert) đều có thể nhầm.

Ticket này build FSM store ở phía control plane: bảng `device_states` lưu trạng thái hiện tại, một engine xử lý event (`device.attached`, `device.online`, `device.busy`, `device.released`, `device.reconnecting`, `device.dead`, ...) đẩy từ agent (DF-E-03) qua heartbeat/state report, áp luật transition để phòng ngừa các bước nhảy bất hợp lệ (ví dụ UNKNOWN không nhảy thẳng ONLINE), ghi lịch sử transition để debug, và expose state hiện tại ra fleet view (DF-T-02-007) cũng như event stream (DF-T-02-015).

P0 vì FSM là backbone của mọi luồng vận hành: claim/release dựa trên state, dispatch của DF-E-04–5 dựa trên state, alert của DF-E-09 dựa trên state. Đặc biệt, ranh giới giữa control plane (ticket này) và agent (DF-E-03) cần được giữ chặt — agent là source of truth cho transition liên quan tới kết nối phần cứng; control plane là source of truth cho transition liên quan tới session (BUSY do session, không phải do agent).

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** xem trạng thái FSM của mỗi thiết bị (UNKNOWN/CONNECTING/ONLINE/BUSY/RECONNECTING/DEAD)
> **Để** chẩn đoán nhanh thiết bị nào cần can thiệp và thiết bị nào sẵn sàng nhận lệnh

Persona phụ: Automation Builder (dispatch dựa trên ONLINE), Platform Engineer (debug drift).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI định nghĩa 6 trạng thái FSM: `UNKNOWN`, `CONNECTING`, `ONLINE`, `BUSY`, `RECONNECTING`, `DEAD` — trace FR-03-04.
- Hệ thống PHẢI mỗi device có đúng một state hiện tại tại mọi thời điểm, lưu trong `device_states` (device_id PK, state, updated_at, last_event_id).
- Hệ thống PHẢI ma trận transition rõ ràng: chỉ chấp nhận chuyển trạng thái hợp lệ; transition bất hợp pháp bị reject với log warning.
- Hệ thống PHẢI lưu lịch sử transition vào `device_state_transitions` (id, device_id, from_state, to_state, event, source, timestamp, payload).
- Hệ thống PHẢI accept event từ agent qua internal channel (in-process pub/sub hoặc message broker) — KHÔNG public HTTP endpoint cho agent push state (sẽ qua channel relay của DF-E-03).
- Hệ thống PHẢI BUSY chỉ được set bởi claim API (DF-T-02-003), không phải agent — agent chỉ báo ONLINE; control plane decide BUSY.
- Hệ thống PHẢI expose state qua field `state` trong response của `GET /api/devices/{id}` và fleet view list — trace FR-02-02.
- Hệ thống PHẢI emit event `device.state_changed` ra event bus cho DF-T-02-015 publish realtime.
- Hệ thống PHẢI dedup event idempotent theo `event_id` để tránh double-apply khi agent retry.
- Hệ thống PHẢI thời gian tồn tại ở state RECONNECTING cấu hình được (default 5 phút) trước khi DF-T-02-005 đẩy sang DEAD.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Transition hợp lệ UNKNOWN → CONNECTING → ONLINE**

```
Given device "df-001" mới pair, state hiện tại = UNKNOWN
When agent emit event device.attached
Then state chuyển CONNECTING
And device_state_transitions có record (from=UNKNOWN, to=CONNECTING, event=device.attached)
When agent emit device.online sau đó
Then state chuyển ONLINE
And event device.state_changed emit ra bus
```

**AC-2: Transition bất hợp lệ bị reject**

```
Given device "df-001" state = UNKNOWN
When event device.busy emit (skip CONNECTING, ONLINE)
Then transition bị reject, log warning "illegal_transition" với from/to/event
And state vẫn UNKNOWN
And metric "fsm.illegal_transition_count" tăng 1
```

**AC-3: BUSY chỉ set bởi claim API**

```
Given device "df-001" state = ONLINE
When claim API (DF-T-02-003) reserve device cho session S1
Then state chuyển BUSY với source="claim", session_id=S1
When agent cố emit event device.busy
Then event bị ignore (source mismatch), log info "agent_busy_event_ignored"
```

**AC-4: Idempotent event apply**

```
Given device "df-001" state = ONLINE
When agent emit cùng event_id="evt-123" event device.busy 2 lần (retry)
Then chỉ apply 1 lần, lần 2 bị dedup
And không có transition trùng trong device_state_transitions
```

**AC-5: Auto-revert BUSY → ONLINE khi session release**

```
Given device "df-001" BUSY do session S1
When session S1 release qua DF-T-02-003
Then state chuyển ONLINE
And device_state_transitions ghi event=session.released
```

**AC-6: State persist sau restart control plane**

```
Given device "df-001" state = BUSY trước restart
When control plane restart
Then sau restart, state đọc từ DB vẫn = BUSY
And không có transition spurious sinh ra trong quá trình restart
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm transport agent → control plane (WebSocket/gRPC) — DF-E-03 (DF-T-03-007).
- KHÔNG bao gồm dead detection logic — DF-T-02-005.
- KHÔNG bao gồm reconnect strategy — DF-T-02-006.
- KHÔNG bao gồm event stream publish ra dashboard — DF-T-02-015 (ticket này chỉ emit ra in-process bus).
- KHÔNG bao gồm claim/release API — DF-T-02-003.
- KHÔNG bao gồm manual state reset — DF-T-02-011.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/devices/fsm.py` — enum State, transition matrix, engine apply event.
- [ ] Module `device_farm/devices/state_store.py` — service đọc/ghi `device_states` + `device_state_transitions`.
- [ ] Internal event consumer subscribe `agent.state_event` topic, gọi engine apply.
- [ ] Emit `device.state_changed` ra bus.

**Frontend** (`layer:frontend`)

- [ ] Không có (state hiển thị ở DF-E-11).

**Contract / API** (`layer:contract`)

- [ ] Bổ sung field `state` vào schema Device trong OpenAPI.
- [ ] Schema event `device.state_changed` cho event stream contract.

**Database / Migration** (`layer:db`)

- [ ] Migration tạo `device_states` (device_id PK, state VARCHAR, updated_at, last_event_id).
- [ ] Migration tạo `device_state_transitions` (id BIGSERIAL, device_id, from_state, to_state, event, source, timestamp, payload JSONB).
- [ ] Index (device_id, timestamp DESC).
- [ ] Backfill state=UNKNOWN cho mọi device tồn tại.

**Infra / DevOps** (`layer:infra`)

- [ ] Cấu hình broker topic nếu dùng external (Redis pub/sub hoặc NATS).
- [ ] Config TTL transition history (giữ 90 ngày, sau đó archive — defer).

**Documentation** (`layer:docs`)

- [ ] `docs/modules/devices.md` mục "FSM" — ma trận transition.
- [ ] Diagram mermaid stateDiagram-v2 (copy từ đặc tả module 5.2).
- [ ] Runbook "Debug FSM drift giữa agent và control plane".

**Test** (`layer:test`)

- [ ] Unit test FSM engine cho mọi cặp (current_state, event) — bảng truth ≥ 36 ô.
- [ ] Integration test 6 AC.
- [ ] Test idempotency với event_id trùng.
- [ ] Test restart persist.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-02-002-01 | Positive | Device state=UNKNOWN | Apply event device.attached | State → CONNECTING; transition row insert |
| TC-DF-T-02-002-02 | Positive | Device state=ONLINE | Claim API set BUSY | State → BUSY; source=claim, session_id ghi |
| TC-DF-T-02-002-03 | Positive | Device state=BUSY | Session release | State → ONLINE |
| TC-DF-T-02-002-04 | Negative | Device state=UNKNOWN | Apply event device.busy | Reject, warning log, state vẫn UNKNOWN |
| TC-DF-T-02-002-05 | Negative | Device state=DEAD | Apply event session.claim | Reject — cần CONNECTING/ONLINE trước; trả lỗi DEVICE_NOT_AVAILABLE |
| TC-DF-T-02-002-06 | Negative | Agent emit device.busy (không qua claim) | Apply | Ignore, log info |
| TC-DF-T-02-002-07 | Edge | Cùng event_id retry 5 lần | Apply | Apply 1 lần, 4 dedup |
| TC-DF-T-02-002-08 | Edge | 1000 device đồng thời transition CONNECTING→ONLINE | Bắn 1000 event | Tất cả apply, không lost, < 5s |
| TC-DF-T-02-002-09 | Edge | Restart control plane khi 50 device BUSY | Restart, query state | 50 device vẫn BUSY, không transition giả |
| TC-DF-T-02-002-10 | Edge | RECONNECTING quá ngưỡng cấu hình | Wait > 5 phút | DF-T-02-005 sẽ chuyển DEAD (ticket này chỉ accept transition); xác minh hook tồn tại |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-001 (cần device record), DF-T-01-008 (observability để log warning hợp lệ).

**Chặn:** DF-T-02-003 (claim đọc state), DF-T-02-005 (dead detection), DF-T-02-007 (fleet view), DF-T-02-013 (stats), DF-T-02-015 (event stream).

**Phụ thuộc giữa Epic:** Tiêu thụ event từ DF-T-03-006 (heartbeat) và DF-T-03-004 (FSM event của agent).

**Rủi ro:**

- **R1 — FSM drift giữa agent và control plane.** Agent thấy ONLINE nhưng control plane vẫn UNKNOWN. Giảm thiểu: reconcile job định kỳ so sánh agent report với store; alert nếu drift > 1 phút.
- **R2 — Event ordering không đảm bảo qua broker.** Giảm thiểu: dùng monotonic event_id sequence per device; reject event cũ hơn last_event_id.
- **R3 — Transition history phình to.** Giảm thiểu: archive partition theo tháng, giữ 90 ngày hot.

**Phụ thuộc bên ngoài:** PostgreSQL ≥ 14 (JSONB), Redis hoặc NATS cho pub/sub.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 90% cho `fsm.py` (logic core).
- [ ] 10 test case automation pass.
- [ ] Transition matrix doc + diagram mermaid trong `docs/modules/devices.md`.
- [ ] Reconcile job có placeholder (chạy hourly so sánh sample).
- [ ] Metric: `fsm.transition_count{from,to}`, `fsm.illegal_transition_count`, `fsm.event_dedup_count`.
- [ ] Audit log emit cho mọi transition (ghi from_state, to_state, source).
- [ ] Performance: apply 1000 event < 5s; query state đơn lẻ < 10 ms.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/02-devices-and-control-plane.md`](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-02, FR-02-13. Cross [`03-agent-boot-and-relay.md`](../../official_docs/modules/03-agent-boot-and-relay.md) — FR-03-04 mục 5.2.
- **Ma trận năng lực:** "Reserve và release device session" (foundation state).
- **Nhóm người dùng:** Fleet Operator, Platform Engineer.
- **Thuật ngữ:** Device session, FSM (Finite State Machine).
- **Liên quan:** DF-T-03-006 (heartbeat feeds event), DF-T-02-005 (dead detection consumes).
