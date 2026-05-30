# DF-T-07-005 — Account state FSM (active / suspended / cooldown / retired / banned)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-005 |
| **Title** | Account state FSM với 5 trạng thái + transition rules |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2` |
| **Truy vết — FR refs** | FR-07-03 |
| **Truy vết — UC refs** | UC-07-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module FR-07-03: "Status account thay đổi giữa các giá trị (ví dụ active, suspended, retired) để phản ánh tình trạng thực tế và loại các account 'đau' ra khỏi rotation." Hiện DF-T-07-001 mới chỉ là field `status` string đơn giản. Ticket này hiện thực hóa **finite state machine (FSM)** đầy đủ với 5 trạng thái và transition rule rõ ràng, để vận hành biết "account này đang ở đâu trong vòng đời" và round-robin (DF-T-07-008) loại đúng account khỏi pool.

Persona hưởng lợi: Social Data Operator (theo dõi account đau, retire account hỏng), Automation Builder (scenario check status trước khi login để fail-fast), Fleet Operator (giải thích vì sao account này không được dùng).

Đặc tả module mục 8 cảnh báo: round-robin không phải load balancer thông minh — không tự đo "account bị nền tảng hạn chế" — nên FSM phải có transition rõ để pipeline ngoài (DF-T-07-006 ban detection) đẩy account đúng trạng thái.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** chuyển account giữa 5 trạng thái (active / suspended / cooldown / retired / banned) với transition rule rõ ràng, mỗi transition có audit log
> **Để** biết account nào đang dùng được, account nào cần nghỉ tạm, account nào đã bỏ vĩnh viễn — và pipeline round-robin loại đúng account

Persona phụ: Automation Builder, Fleet Operator.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI hỗ trợ 5 trạng thái:
  - `active`: sẵn sàng dùng, đủ điều kiện round-robin.
  - `cooldown`: tạm nghỉ có hạn (vd 24h sau khi platform báo rate limit); tự động transition `active` khi hết TTL.
  - `suspended`: nghi vấn (vd ban detection trả signal); người vận hành quyết định manual.
  - `banned`: nền tảng đã ban; không tự bỏ; chỉ retire được.
  - `retired`: đã ngừng vĩnh viễn; không round-robin; vẫn giữ để truy vết.
- Hệ thống PHẢI enforce transition rule:
  - `active` → `cooldown` (auto signal hoặc manual), `suspended`, `banned`, `retired`.
  - `cooldown` → `active` (auto khi hết TTL), `suspended`, `retired`.
  - `suspended` → `active` (manual unblock), `banned`, `retired`.
  - `banned` → `retired` (chỉ).
  - `retired` → ❌ (terminal, không quay lại).
- Hệ thống PHẢI từ chối transition không hợp lệ với error `INVALID_STATE_TRANSITION` và message rõ.
- Hệ thống PHẢI có endpoint `POST /api/accounts/{id}/state` body `{to, reason, ttl_seconds?}` — trace FR-07-03.
- Hệ thống PHẢI lưu cột `state`, `state_reason`, `state_changed_at`, `cooldown_until` trong bảng `accounts` (migration).
- Hệ thống PHẢI có job định kỳ (Temporal cron 1 phút) check `cooldown_until <= now` → auto transition về `active`.
- Hệ thống PHẢI emit domain event `account.state.changed {account_id, from, to, reason, ttl, actor}`.
- Hệ thống PHẢI loại account không ở status `active` khỏi round-robin (DF-T-07-008 dùng).
- Hệ thống PHẢI audit mọi state change vào DF-T-07-011.
- Hệ thống NÊN expose metric `account_state_total{platform, state}` cho dashboard.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Transition active → cooldown với TTL**

```
Given account A status="active"
When U POST /api/accounts/A/state {to:"cooldown", reason:"FB rate limit", ttl_seconds:86400}
Then trả 200; A.state="cooldown", cooldown_until=now+24h
And event account.state.changed phát
And A bị loại khỏi round-robin
```

**AC-2: Auto transition cooldown → active khi hết TTL**

```
Given account A state="cooldown", cooldown_until=2026-05-26T10:00:00
When cron job chạy lúc 10:01:00
Then A.state="active", cooldown_until=null
And event phát từ actor="system"
And A xuất hiện lại trong round-robin
```

**AC-3: Transition không hợp lệ retired → active**

```
Given account A state="retired"
When U POST state {to:"active"}
Then 422 INVALID_STATE_TRANSITION với message "retired là terminal state"
And A.state vẫn "retired"
```

**AC-4: Banned chỉ retire được**

```
Given account A state="banned"
When U POST state {to:"active"}
Then 422 INVALID_STATE_TRANSITION
When U POST state {to:"retired", reason:"FB confirmed ban 2026-05"}
Then 200; A.state="retired"
```

**AC-5: Round-robin loại non-active**

```
Given group G có 5 account: a1,a2 active; a3 cooldown; a4 suspended; a5 banned
When call round-robin endpoint 10 lần
Then chỉ a1, a2 được trả về (luân phiên)
And a3/a4/a5 KHÔNG xuất hiện
```

**AC-6: Audit transition**

```
Given U thực hiện 3 transition liên tiếp
When U query audit log /api/audit?account_id=A
Then 3 entry với actor=U, from→to, reason, timestamp
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm ban detection signal (DF-T-07-006).
- KHÔNG bao gồm warmup workflow (DF-T-07-009).
- KHÔNG bao gồm round-robin endpoint (DF-T-07-008) — chỉ guarantee account ngoài active không xuất hiện.
- KHÔNG bao gồm UI dashboard chi tiết — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] FSM engine `AccountStateMachine` với transition matrix.
- [ ] Service `AccountStateService.transition(account_id, to, reason, ttl)`.
- [ ] Temporal cron worker `CooldownTickWorker`.
- [ ] Event publisher.
- [ ] Filter `active`-only trong query default (params `include_states=[]` để override).

**Contract / API** (`layer:contract`)

- [ ] OpenAPI endpoint POST state.
- [ ] Mã lỗi `INVALID_STATE_TRANSITION`.
- [ ] Event schema `account.state.changed`.

**Database / Migration** (`layer:db`)

- [ ] Migration thêm cột `state`, `state_reason`, `state_changed_at`, `cooldown_until`.
- [ ] Backfill `state="active"` từ DF-T-07-001.
- [ ] Index `(state, cooldown_until)` cho cron query nhanh.

**Documentation** (`layer:docs`)

- [ ] FSM diagram trong `docs/modules/accounts.md`.
- [ ] Transition matrix table.
- [ ] Runbook "Khi account bị FB checkpoint".

**Test** (`layer:test`)

- [ ] Unit test FSM transition matrix (tất cả combination).
- [ ] Integration test cron cooldown.
- [ ] Test round-robin chỉ trả active.
- [ ] Test event phát đúng.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-07-005-01 | Positive | Account A active | POST state {to:"cooldown", ttl:3600} | 200; state="cooldown"; cooldown_until=+1h |
| TC-DF-T-07-005-02 | Positive | Account A cooldown, TTL hết | Cron tick | Auto → active; event phát |
| TC-DF-T-07-005-03 | Positive | Account A banned | POST state {to:"retired"} | 200; A.state="retired" |
| TC-DF-T-07-005-04 | Negative | Account A retired | POST state {to:"active"} | 422 INVALID_STATE_TRANSITION |
| TC-DF-T-07-005-05 | Negative | Account A banned | POST state {to:"active"} | 422 INVALID_STATE_TRANSITION |
| TC-DF-T-07-005-06 | Edge | Cooldown TTL=0 hoặc âm | POST state {to:"cooldown", ttl:-1} | 422 INVALID_TTL |
| TC-DF-T-07-005-07 | Edge | Concurrent transition 2 user đồng thời | POST state đồng thời | 1 success, 1 trả 409 STATE_CONFLICT (optimistic lock) |
| TC-DF-T-07-005-08 | Edge | 1000 account cooldown hết TTL cùng lúc | Cron tick | Tất cả transition active; không miss; latency < 30s |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001 (account model).

**Chặn:** DF-T-07-006 (ban detection ghi state), DF-T-07-008 (round-robin filter), DF-T-07-009 (warmup ghi state).

**Phụ thuộc giữa Epic:** DF-E-04 (dispatch consume event để skip account); DF-E-09 (notification khi state critical).

**Rủi ro:**

- **Cron miss cooldown khi cluster restart:** giảm thiểu: query bù khi worker khởi động (`WHERE cooldown_until <= now AND state='cooldown'`).
- **Race condition transition đồng thời:** giảm thiểu: optimistic locking trên `state_changed_at`.
- **State drift giữa DB và cache:** giảm thiểu: event-driven invalidation cache.

**Phụ thuộc bên ngoài:** Temporal (cron worker).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 85% FSM logic.
- [ ] FSM transition matrix viết doc + diagram.
- [ ] Cron cooldown test pass với 1000 account.
- [ ] Event consumer trong DF-E-04 verify được.
- [ ] Telemetry `account_state_total{platform,state}` + `state_transition_total{from,to,reason}`.
- [ ] Code review ≥ 1 owner module.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md §6 FR-07-03, §8 round-robin not smart](../../official_docs/modules/07-accounts-and-groups.md).
- **Nhóm người dùng:** Social Data Operator (§3.1).
- **Thuật ngữ:** [Account state](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-04, DF-E-09.
