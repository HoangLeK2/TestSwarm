# ADL-10 — Immutable build, issue và retest lineage production

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | BE domain + FE / runtime/DB + product + QA |
| Dependencies | 04 contract; integration 07/08/17; 09 retest pricing/policy |
| Deliverable | AppBuild/Issue/Retest models/API/UI, immutable compare và quota linkage |

## 2. Source/gap
`backend/db/models/{execution,scenario_version}.py` có execution/version refs, không thay AppBuild+Issue domain. App build schema/interface phải chốt D1 cùng 04, không đợi dashboard xong mới định nghĩa FK.

## 3. Contract
- AppBuild immutable: org/package, declared versionCode/versionName/source/created_at/checksum khi artifact có; installed build observations riêng mỗi attempt.
- Issue: org/campaign, severity enum do product duyệt, expected/actual/repro, source_attempt, source step/selector, device/build/scenario/artifact refs; duplicate fingerprints hỗ trợ review, không auto-merge cross-build.
- RetestRequest: source issue/attempt, target build/approved scenario, scope lanes, idempotency key, quota/cost consent và status.
- Verdict fixed/still_failing/inconclusive chỉ từ cùng assertion/reproduction scope với actual build match; blocked/timeout/no assertion không fixed. History issue transitions append audit.

## 4. Bước làm
1. Chốt build interface sớm với 04/16; implement migration/FKs và permission errors.
2. Create builds/observations, source issue extraction từ evaluated attempts, edit triage metadata có audit.
3. Retest preview tính quota/cost, authorization/consent, idempotent dispatch through 16, không tạo scheduler riêng.
4. Compare UI old/new expected/observed/build/evidence và verdict reason; URLs re-sign khi đọc.
5. Lineage/race/isolation tests và browser real run fail→retest proof.

## 5. Acceptance
- [ ] AC1: declared và observed build độc lập; mismatch không kết luận fixed.
- [ ] AC2: issue/retest truy từ source attempt tới new attempt với immutable refs.
- [ ] AC3: cost/quota consent trước dispatch; duplicate không tiêu hai lần.
- [ ] AC4: verdict dựa assertion, blocked=inconclusive.
- [ ] AC5: old history/evidence vẫn truy cập và scoped.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 10-T1 | v1 fail→same assertion v2 pass | fixed có new/source links; v1 unchanged |
| 10-T2 | Retest offline/OTP/no assertion | inconclusive, không fixed |
| 10-T3 | Device installed v1 dù target v2 | mismatch rõ, rejected/inconclusive |
| 10-T4 | Two retest submits same key | One request/grant consumption/attempt intent |
| 10-T5 | Old capture reopen after TTL | Same object/history, fresh URL |
| 10-T6 | Cross-org build/issue/attempt association | Reject; no orphan retest |

## 7. Review và DoD
Domain/DB reviewer kiểm FK/immutability, product severity/verdict, QA replay T1–6 và compare UI. Lưu source/retest row IDs, quota ledger, screenshot/video refs và commands. Fail → REWORK, không đưa fixed vào report; rerun affected lineage/cost tests. DONE cần AC1–5 và observed build proof.
