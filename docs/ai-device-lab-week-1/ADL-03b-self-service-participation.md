# ADL-03b — Participation ledger và customer/operator workflow production

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | BE domain + FE / DB + security + QA + product |
| Dependencies | 02, 03a evidence protocol; 15 role contract áp dụng trước release |
| Deliverable | Models/events, evidence upload/review API, cohort UI, continuity read-model |

## 2. Source/gap
`backend/db/models/account.py` quản account farm; `backend/db/models/execution.py` trỏ account cho run. Không có model Play participation/continuity proven. Tái dùng auth/tenant/artifact storage; không dùng execution success làm enrollment source.

## 3. Contract
- TrackParticipation unique org+package+track+canonical pseudonymous account identity, không unique theo serial. Mask email chỉ là presentation, không dùng masked email làm unique key vì có collision.
- Append-only ParticipationEvent: invited/opted_in/observed/lost/rejoined/unknown, source, observed_at, recorded_at, actor/reviewer, evidence ref và continuity segment.
- Read-model có current status, last observed time, evidence grade và gaps; late/corrected observations không rewrite events, cần correction event và reviewer.
- Private evidence upload có size/type limits, authorized object ownership và access audit; raw identity scope riêng, reports chỉ pseudonym.

## 4. Bước triển khai
1. DB review identity/uniqueness/events/time semantics; migration và fixtures 12 identities + duplicates.
2. CRUD/read cohort, append observation, upload evidence, operator review/reject/correction; permissions theo 15.
3. Compute continuity segments từ verified/attested events, explicitly label observation limitations; không khẳng định Google count.
4. Customer list/detail + operator review queue EN/VI; unknown/stale/lost có next action.
5. Test out-of-order/collision/tenant/upload flows; nối readiness contract 06 và dashboard 08.

## 5. Acceptance
- [ ] AC1: 12 distinct account identities được đếm, duplicates không tăng count.
- [ ] AC2: continuity mất khi opt-out; re-opt-in không cộng segment cũ.
- [ ] AC3: status luôn mang source/grade/time/gap; không auto-verify từ run/group.
- [ ] AC4: scoped upload/read/review; immutable event history và correction audit.
- [ ] AC5: UI/API thống nhất và customer không tự đổi status thành reviewer-approved.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 03b-T1 | 12 accounts + repeat same identity trên device khác | Count 12; không 13 |
| 03b-T2 | Lost/rejoined sequence | New continuity start; old history preserved |
| 03b-T3 | Late observation/correction | Recorded vs observed time rõ; reviewer correction có audit |
| 03b-T4 | Customer self approve/org B evidence download | Denied; no URL leak |
| 03b-T5 | Masked identity collision và file type/size invalid | Không merge nhầm người; validation reject |
| 03b-T6 | Evidence stale/gap nhưng all runs passed | Participation unknown/stale; no eligible label |

## 7. Review và DoD
DB reviewer ký identity/event rules, security upload/privacy, product trust wording; QA replay six cases + browser. Evidence migrations, API cases, SQL count/event history, UI recordings và private proof refs. Fail → REWORK → re-evaluate cohort/readiness impacted. DONE khi AC1–5 PASS; không dùng operator spreadsheet để đóng task.
