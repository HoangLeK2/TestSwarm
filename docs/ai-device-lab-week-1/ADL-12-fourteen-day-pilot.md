# ADL-12 — Nghiệm thu vận hành production đủ chu kỳ 14 ngày

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production G2 mandatory / NOT_STARTED |
| Owner / review | Operator + QA lead / product + runtime + security |
| Dependencies | Functional ADL-00…19, 20a/20b, 21 đạt G1; không phụ thuộc 20c |
| Deliverable | Daily reconciliation 14 ngày, exceptions/audits, final report và KPI source evidence |

## 2. Preflight/input
12 distinct lane reservations, healthy/hygiene devices, approved scenario/build, cohort participation theo service contract, billing/entitlement và environment đủ; protocol nguồn Play của 03a/b. Ghi started_at UTC, window/timezone, software versions, operator rota và escalation channels. Chưa đủ một input thì không start/backdate.

## 3. Quy trình vận hành
1. D0 freeze plan/definitions/retention/KPI/cohort; check G1 evidence với reviewer.
2. Mỗi 24h service window: planned 12 slots, reconcile attempted/terminal/evaluated/blocked/missed/retry/quota từ DB/API; Approved Device Target spot-check identity/evidence theo rota.
3. Ghi account observations/source/gaps riêng; opt-out/re-opt-in không sửa service timeline hoặc tự ghép continuity.
4. Inject failure có kiểm soát trong staging/cohort được duyệt: offline, replacement, build update, OTP, missing evidence; destructive fault chỉ test systems cho phép, không tự phá customer runs.
5. Daily QA sign-off và triage incident; report cần nêu skipped/missed/source uncertainty, không backfill pass.
6. Cuối đủ 14 windows: drain/release/hygiene, snapshot report, KPI calculations, daily manifest và handover 20c.

## 4. Acceptance
- [ ] AC1: ≥14 ngày elapsed thực từ start hợp lệ, đủ daily records và source cutoff.
- [ ] AC2: 168 planned slots và outcome/retry/quota reconcile; không xóa failed/missed.
- [ ] AC3: participation limitations/continuity events đúng, không claim Google approval.
- [ ] AC4: cancel/expire/replace/cleanup và customer journey có live evidence.
- [ ] AC5: final report/KPI cohort thật và incident log được reviewer xác nhận.

## 5. Test matrix / diễn tập
| ID | Thời điểm/action | Expected / evidence |
|---|---|---|
| 12-T1 | Daily D1–D14 reconciliation | 12 expected slots/day, attempts/quota/source links; reviewer timestamp |
| 12-T2 | Controlled opt-out/rejoin case được phép | New continuity segment; no silently eligible count |
| 12-T3 | Offline/missed/replacement | Explicit exceptions; same lane/history; no fake pass |
| 12-T4 | Build v2 retest + old artifact reopen | Immutable compare + readable old evidence |
| 12-T5 | Cancel mid-cycle diễn tập ở separate test campaign | Stop future slots, drain/release/hygiene, audit/refund policy |
| 12-T6 | D14 report/KPI/export org B attempt | Reconciled final snapshots; tenant rejection |

## 6. Review và DoD
Daily QA/operator ký record; unresolved incident có owner/next update. G2 fail nếu thời gian/evidence/account source thiếu; extension theo consent tạo policy delta, không sửa ngày gốc. Lưu private daily manifests/API/DB/browser/device-target/provider refs và timestamps, không commit credentials. DONE khi AC1–5 PASS; không thay 14-day evidence bằng clock simulation; 20c quyết launch sau đó.
