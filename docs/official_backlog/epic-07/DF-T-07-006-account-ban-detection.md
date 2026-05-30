# DF-T-07-006 — Account ban / checkpoint detection signal

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-006 |
| **Title** | Account ban / checkpoint detection signal + quarantine flow |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:contract`, `type:feature`, `platform:facebook`, `platform:tiktok`, `platform:threads`, `platform:instagram`, `persona:social-data-operator`, `coverage:L3`, `risk:platform-tos` |
| **Truy vết — FR refs** | Lộ trình ban detection, FR-07-03 status transition |
| **Truy vết — UC refs** | UC-07-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 8 nói rõ: "Cơ chế round-robin của module chỉ đảm bảo cấp phát đều. Hệ thống không tự đo 'account nào đang bị nền tảng social hạn chế', không tự 'ấm máy' account mới, và không tự dừng account khi phát hiện CAPTCHA. Các logic này thuộc scenario hoặc thuộc đội vận hành." Ticket này cung cấp **signal ingestion API** để scenario (DF-E-08 platform-specific step) đẩy tín hiệu vào hệ thống, và FSM (DF-T-07-005) tự quarantine account theo policy.

Platform-specific quirks cần xử lý theo Facebook checkpoint, TikTok challenge, Instagram action-blocked, Threads suspended. Mỗi platform có signal kiểu khác nhau; ticket này định nghĩa **unified signal schema** + per-platform mapping.

Persona hưởng lợi: Social Data Operator (account đau bị tự skip), Automation Builder (scenario chỉ cần report signal, không phải biết FSM transition logic).

Đọc nhanh cho dev: ticket này nhận signal từ scenario/platform step rồi chuyển account state qua policy. Không tự detect ban bằng crawler riêng; phần chính là unified signal schema, per-platform mapping, aggregation, dismiss false positive và event cho DF-E-09.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** scenario step phát hiện checkpoint/challenge/ban có thể push signal `account_ban_detected` với evidence (screenshot, hierarchy snippet, platform code)
> **Để** hệ thống tự transition account sang `suspended` hoặc `banned` theo policy, không phải Social Data Operator vào sửa thủ công

Persona phụ: Social Data Operator (xem signal log để hiểu vì sao account bị quarantine).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có endpoint `POST /api/accounts/{id}/signals` body `{signal_type, severity, evidence, platform_code, source_step}`.
- Hệ thống PHẢI hỗ trợ signal_type: `checkpoint_detected`, `challenge_required`, `action_blocked`, `login_failed`, `captcha_required`, `account_disabled`, `rate_limited`.
- Hệ thống PHẢI có per-platform mapping signal → state transition:
  - Facebook: `checkpoint_detected` (sev=high) → `suspended`; `account_disabled` → `banned`.
  - TikTok: `challenge_required` (sev=medium) → `cooldown 24h`; `account_disabled` → `banned`.
  - Threads: `account_disabled` → `banned`; tương tự FB checkpoint.
  - Instagram: `action_blocked` (sev=medium) → `cooldown 6h`; `account_disabled` → `banned`.
- Hệ thống PHẢI lưu bảng `account_signals(id, account_id, signal_type, severity, evidence_artifact_id, platform_code, source_execution_id, source_step_index, created_at)`.
- Hệ thống PHẢI signal aggregation: 3 signal severity=medium trong 1 giờ → escalate `suspended`.
- Hệ thống PHẢI gọi `AccountStateService.transition()` (DF-T-07-005) theo policy mapping; nếu transition không hợp lệ (vd đã banned) thì log skip, không lỗi.
- Hệ thống PHẢI link signal với artifact (DF-E-06): evidence_artifact_id trỏ về screenshot/hierarchy snapshot tại thời điểm phát hiện — trace truy vết.
- Hệ thống PHẢI cho phép manual `POST /api/accounts/{id}/signals/dismiss` để vận hành quyết định false positive — log audit.
- Hệ thống PHẢI emit event `account.signal.received` để DF-E-09 notify operator.
- Hệ thống PHẢI cho phép tenant cấu hình policy mapping (override default) qua config — `account_signal_policy.yaml` per organization.
- Hệ thống NÊN expose `GET /api/accounts/{id}/signals` để Social Data Operator xem timeline signal.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Facebook checkpoint signal → suspended**

```
Given account A platform="facebook" state="active"
When scenario step push POST /api/accounts/A/signals
   body {signal_type:"checkpoint_detected", severity:"high",
         evidence_artifact_id:"art_123", platform_code:"FB_CKPT_601",
         source_step:"check_feed"}
Then trả 201 signal_id
And A.state transition → "suspended" với reason="signal:checkpoint_detected"
And event account.signal.received phát
And event account.state.changed phát
```

**AC-2: Aggregation 3 signal medium → escalate**

```
Given account A active, có 2 signal severity=medium trong 30 phút qua
When signal thứ 3 medium đến
Then aggregator phát hiện
And A.state transition → "suspended"
And reason="signal_aggregation: 3 medium in 1h"
```

**AC-3: Manual dismiss signal — không transition**

```
Given operator nghi signal là false positive
When U POST /api/accounts/A/signals/{sig_id}/dismiss reason="UI bug FB version"
Then signal đánh dấu dismissed
And A.state không transition do signal này
And audit log entry "signal_dismissed" với U + reason
```

**AC-4: Per-tenant policy override**

```
Given organization X có policy custom: TikTok challenge → cooldown 12h (default 24h)
When TikTok signal challenge_required đến cho A trong org X
Then A → cooldown với TTL 12h (không phải 24h default)
```

**AC-5: Signal trùng — idempotent**

```
Given scenario step retry và push signal trùng (cùng execution_id + step_index)
When POST /signals lần 2
Then 200 với existing_signal_id; không tạo row mới; không transition lại
```

**AC-6: Signal aggregation reset sau cooldown**

```
Given A đã có 2 signal medium → vừa kết thúc cooldown
When signal medium thứ 3 đến sau khi A active lại
Then KHÔNG aggregate với signal cũ (counter reset sau transition)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm captcha solving — ngoài phạm vi module.
- KHÔNG bao gồm "tự warmup account" sau khi suspended — DF-T-07-009.
- KHÔNG bao gồm UI dashboard signal — DF-E-11.
- KHÔNG bao gồm AI-based ban prediction — không trong scope.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Model `AccountSignal`.
- [ ] Service `SignalIngestionService` với per-platform policy.
- [ ] Aggregator `SignalAggregator` (sliding window 1h).
- [ ] Policy loader `account_signal_policy.yaml` per org.
- [ ] Idempotency check theo (execution_id, step_index, signal_type).

**Contract / API** (`layer:contract`)

- [ ] OpenAPI: POST signals, GET signals, POST dismiss.
- [ ] Event schema `account.signal.received`.
- [ ] Schema policy YAML.

**Database / Migration** (`layer:db`)

- [ ] Bảng `account_signals`.
- [ ] Index (account_id, created_at), (signal_type, severity).

**Documentation** (`layer:docs`)

- [ ] Per-platform mapping default table.
- [ ] "How to write platform-specific ban detection" guide cho Automation Builder.
- [ ] Runbook khi account bị banned: triage flow.

**Test** (`layer:test`)

- [ ] Test 4 platform mapping default.
- [ ] Test aggregation window.
- [ ] Test idempotency.
- [ ] Test policy override.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-07-006-01 | Positive | FB account A active | Push checkpoint_detected high | A → suspended; event 2 |
| TC-DF-T-07-006-02 | Positive | TikTok A active | Push challenge_required medium | A → cooldown 24h |
| TC-DF-T-07-006-03 | Positive | IG A active | 3 action_blocked medium trong 1h | A escalate → suspended |
| TC-DF-T-07-006-04 | Negative | A đã banned | Push checkpoint high | Signal lưu; transition skip (đã terminal); log warn |
| TC-DF-T-07-006-05 | Negative | Cross-tenant push signal | POST signal account khác org | 404 |
| TC-DF-T-07-006-06 | Edge | Retry idempotent | Push 2 lần cùng (exec_id, step_idx) | Lần 2 trả existing; không transition lại |
| TC-DF-T-07-006-07 | Edge | Org X override TikTok cooldown=12h | Push TikTok challenge | A cooldown 12h (không 24h) |
| TC-DF-T-07-006-08 | Edge | False positive dismiss | Operator dismiss signal | Không transition; audit |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-005 (FSM transition API), DF-T-07-001 (account model), DF-E-06 DF-T-06-002 (artifact ID cho evidence).

**Chặn:** DF-E-08 (platform-specific step push signal).

**Phụ thuộc giữa Epic:** DF-E-06 (artifact storage); DF-E-09 (notification consume event).

**Rủi ro:**

- **False positive bóc nhiều account oan:** giảm thiểu: aggregation window + dismiss flow + severity classification.
- **Platform thay đổi mã lỗi → policy lỗi thời:** giảm thiểu: policy YAML version per platform, doc update khi platform change.
- **Signal flood DDoS (scenario buggy push 1000 signal/s):** giảm thiểu: rate limit per-account 10 signal/phút; deduplication.

**Phụ thuộc bên ngoài:** Platform-specific knowledge per Facebook/TikTok/Threads/Instagram (xem `docs/official_docs/platforms/*.md`).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] 4 platform default policy hoạt động trong test.
- [ ] Policy YAML schema validate trong CI.
- [ ] Aggregation window test pass với 1000 signal concurrent.
- [ ] Telemetry: `signal_received_total{platform,type,severity}`, `signal_transition_total{action}`.
- [ ] Doc per-platform mapping published.
- [ ] Code review ≥ 1 owner module + 1 platform engineer.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md §8 round-robin not smart](../../official_docs/modules/07-accounts-and-groups.md).
- **Platforms:** [facebook.md](../../official_docs/platforms/facebook.md), [tiktok.md](../../official_docs/platforms/tiktok.md), [instagram.md](../../official_docs/platforms/instagram.md), [threads.md](../../official_docs/platforms/threads.md).
- **Nhóm người dùng:** Automation Builder (§3.2), Social Data Operator (§3.1).
- **Epic liên quan:** DF-E-06, DF-E-08, DF-E-09.
