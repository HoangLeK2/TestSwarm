# ADL-20c — Production launch acceptance và quyết định go/no-go

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production G3 mandatory / NOT_STARTED |
| Owner / reviewers | QA lead / product owner + security + operations lead |
| Dependencies | Tất cả ADL-00…19, 20a/20b, 21 và ADL-12 G2 đủ thời gian thật |
| Deliverable | Versioned acceptance pack, requirement/evidence matrix, signed launch decision |

## 2. Evidence contract
Mỗi requirement có ADL/AC/test IDs, environment/commit/schema version, tester/reviewer, execution time, expected/observed, API/DB/browser/device-target/provider/Play evidence refs theo loại thực sự cần. Mức source-only/mock/sandbox/live phải ghi, không dùng source inspection thay Approved Device Target/payment proof.

Pack có scope, exclusions do **chủ sở hữu** duyệt, open defects/severity, unresolved blockers, KPI source/cohort, retention/SLO/RPO/RTO measured, launch/rollback/on-call owners. Report Google production access chỉ khi có external verified source, không diễn dịch G3 của dịch vụ thành approval Google app.

## 3. Bước nghiệm thu
1. Freeze candidate/version và inventory tất cả AC/tasks; không cherry-pick happy path.
2. QA độc lập replay full customer→operator journey và critical negative/race/recovery cases.
3. Reconcile 14-day daily manifests, 168 slots/attempts/quota, issues/retest/report/PDF và real KPI.
4. Security review secret/tenant/export/PII; operations kiểm restore/rollback/alerts/on-call và payment production readiness.
5. Findings quay về đúng task/owner, sửa/retest affected flows; version candidate đổi thì pack cập nhật và reviewed again.
6. Product/QA/security/ops ký PASS hoặc NO_GO có lý do; incomplete evidence không được ghi PASS.

## 4. Acceptance
- [ ] AC1: mỗi required AC có evidence/reviewer và không unresolved blocker.
- [ ] AC2: 14-day G2 và final report reconciliation thật đầy đủ.
- [ ] AC3: no double billing/booking, unauthorized read/action, secret leak hoặc false pass.
- [ ] AC4: operational/financial readiness và recovery đã đo/rehearsal.
- [ ] AC5: signed launch decision versioned, rollback/on-call ownership rõ.

## 5. Release-blocking case matrix
| ID | Verification | Expected |
|---|---|---|
| 20c-T1 | Concurrent reserve/checkout/replay | No double device allocation/charge/grant/job |
| 20c-T2 | Offline/OTP/no assertion→human resume | Blocked/inconclusive honest, source recheck required |
| 20c-T3 | Old build/retry/media→final report | Immutable history, correct full-source counts |
| 20c-T4 | Cross-org/role revoke/secret capability | Deny scope violation, no leakage |
| 20c-T5 | 14-day elapsed/Play unknown evidence | No false continuous-account/Google approval claim |
| 20c-T6 | Real KPI measurement + missing trace | Explicit denominators; thresholds evaluated, not presumed |
| 20c-T7 | Outage/restore/rollback/cancel/hygiene | Source/payment preserved, no unsafe reuse, owner response |

## 6. Review và DoD
QA lead signs case completeness, security boundary, ops readiness, product service scope/claims. Evidence references phải reachable/authorized trong retention window. NO_GO→task REWORK/BLOCKED→fix→replay→candidate/pack version mới→review lại. DONE chỉ khi AC1–5 PASS, không bỏ gate để đạt target một tuần.
