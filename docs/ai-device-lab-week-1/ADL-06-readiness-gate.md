# ADL-06 — Readiness và Start/resume nguyên tử server-side

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | BE service + FE / security + domain + QA |
| Dependencies | 03b, 04, 05, 09, 18a/18b; 15 authorization contract |
| Deliverable | Versioned checklist, start transaction, stale-check guard, human-assist resume UI |

## 2. Source/gap
Campaign dispatch routes/runtime state đã có; chưa có service gate nối approved version/payment/reservation/account/build. Không dùng client-side disabled button làm authorization. Need integration chứ không tạo thêm independent dispatcher.

## 3. Contract
ReadinessCheck có key/status(required_pass/blocked/unknown/not_applicable), required flag, reason_code, observed_at, source_ref/version, owner/next_action; applicability từ service plan, không từ client. Snapshot có revision/expiry.

Start server transaction revalidates entitlement còn hiệu lực, exact approved scenario+policy, 12 reservations/healthy/hygiene, preflight package/version, participation evidence theo gói, secret references nếu app cần. Lock campaign/idempotency; set started_at một lần rồi tạo scheduling intent/outbox, không remote dispatch trước commit. Paid_at khác started_at. Stale UI snapshot phải re-check.

Resume sau OTP/human assistance re-check required blockers; không tự sửa app assertion từ failed thành passed. Mất entitlement/reservation/secret giữa runs chặn slot tiếp theo và giữ history.

## 4. Bước làm
1. Product/security ký required/applicability matrix và freshness thresholds; unresolved → BLOCKED_DECISION.
2. Build checker interface dùng persisted source+preflight provenance; record lý do chi tiết không chứa credentials.
3. Start/resume transactional commands + repeat result/error contracts; phối hợp 07/16 delivery outbox.
4. UI checklist/action ownership và retry checks; Start trạng thái lấy server.
5. Tests barrier race, stale snapshot, revoked source và browser blocked→fixed→ready.

## 5. Acceptance
- [ ] AC1: tất cả checks có status/source/time/reason, unknown không biến pass.
- [ ] AC2: direct API không bypass payment/scenario/12th device/secret.
- [ ] AC3: repeated/concurrent Start có một start time/scheduling intent.
- [ ] AC4: stale source hoặc revoked entitlement được phát hiện trước action.
- [ ] AC5: resume có human-assist audit + recheck, không đổi old verdict.

## 6. Test matrix
| ID | Setup/action | Expected |
|---|---|---|
| 06-T1 | Fail từng required check trong table fixtures | Start denied với correct reason/next action |
| 06-T2 | Paid nhưng scenario chưa duyệt hoặc chỉ 11 máy | No started_at/no scheduling intent |
| 06-T3 | Hai Start processes cùng key | Một started_at/intent; repeat response consistent |
| 06-T4 | Revoke payment/approval sau UI snapshot trước Start | Atomic check rejects; no job |
| 06-T5 | OTP blocked→human fix→resume | Source refreshed, audit actor; same history retained |
| 06-T6 | Credential expired/cross-org ref | Denied; no plaintext in error |

## 7. Review và DoD
Security kiểm server paths, domain reviewer transaction/outbox, product ký applicability và QA replay blockers. Evidence checklist revision, SQL timestamps/intent counts, denial responses và browser recovery. Fail → REWORK → rerun matrix liên quan. DONE cần AC1–5; Start readiness không tự chứng minh 14-day eligibility Google.
