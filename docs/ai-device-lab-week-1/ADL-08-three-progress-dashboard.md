# ADL-08 — Dashboard production và lane/attempt detail

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | FE + BE read-model / product + QA + security |
| Dependencies | 03b, 07; evidence manifest interface 17; permissions 15 |
| Deliverable | Scoped roll-up API, dashboard/detail UI EN/VI, reconciliation/browser tests |

## 2. Source/gap
`backend/services/execution_trace.py` enriches execution/steps/events nhưng giới hạn trang; campaign monitor FE là technical runtime UI. Cần service-slot/ledger/participation views, không dùng UI event count làm tổng toàn campaign.

## 3. Contract UI/read-model
- Service card: day/time window, planned slots, attempted/terminal/missed, actual quota/extra retest, campaign state.
- App quality card: evaluated/pass/fail/inconclusive; denominator explicit. Blocked không nằm numerator pass.
- Play card: distinct account identities, status/grade/last observed/gaps; không suy eligible từ run completion.
- Lane detail: assignment history → slot → ordered attempts → observed build/scenario version → steps expected/observed → manifest media status.
- APIs có total/pagination/cutoff; aggregation trên DB source toàn cohort. URLs không long-lived cache; missing/unsupported/expired có next action.

## 4. Bước làm
1. Lock aggregation definitions với 07/20b; DTO dùng generated client và tenant filters server-side.
2. Build fixtures 168 slots gồm retries/offline/replacement/missing evidence để tính tay counts.
3. Implement dashboard and drill-down, loading/error/empty/stale state, responsive/focus/EN/VI.
4. Refresh/poll events không duplicate/counter drift; re-sign URL lúc mở media và handle 410.
5. Reconcile UI/API/SQL; browser desktop/mobile + expired/revoked access.

## 5. Acceptance
- [ ] AC1: ba nguồn progress độc lập, counts và denominator truy về DB được.
- [ ] AC2: mỗi lane/attempt giữ lịch sử device/build/scenario.
- [ ] AC3: missing evidence không giả ảnh/video tồn tại.
- [ ] AC4: scoped reads/URLs, no secret/raw Play identity leak.
- [ ] AC5: responsive EN/VI và recovery lỗi/TTL hoạt động.

## 6. Test matrix
| ID | Setup/action | Expected |
|---|---|---|
| 08-T1 | 168 slots + 2 retries + failures fixture | Slot count 168; attempt count riêng; pass denominator evaluated |
| 08-T2 | All runs pass, enrollment Unknown | Play remains Unknown; no Google eligible badge |
| 08-T3 | Missing/expired/video unsupported manifest | Đúng labels; không fake thumbnail/player |
| 08-T4 | Org B direct detail/artifact API | Denied; URL không cấp |
| 08-T5 | Repeat/reordered live events + refresh | No duplicated UI rows/count drift |
| 08-T6 | Keyboard/mobile/EN/VI + reopen after TTL | Focus, translated labels, new URL/readable error |

## 7. Review và DoD
QA tính tay SQL vs API/UI, product kiểm wording/next actions, security thử cross-tenant. Evidence fixtures, queries/counts, browser recording và API denial. Finding → REWORK → rerun counts+browser affected. DONE khi AC1–5 PASS; KPI cohort production proof thuộc 20b/12.
