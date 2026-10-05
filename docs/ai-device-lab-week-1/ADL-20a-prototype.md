# ADL-20a — Production UX specification và user validation

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production design gate / NOT_STARTED |
| Owner / review | UX/FE + product / developer participant + operator + accessibility reviewer |
| Dependencies | Source PRD and service constraints; mock-state design có thể bắt đầu D1 |
| Deliverable | Screen/state specification, clickable prototype, user-test findings and signed decisions |

## 2. Source/gap
Campaign monitor/auth/device UI hiện hữu; deck có landing/wizard/dashboard/detail/report. Không đủ chỉ vẽ happy path; cần states/roles/errors/price/quota/privacy và next action. Prototype không đóng chức năng API/runtime của các task khác.

## 3. Design contract
| View | States tối thiểu |
|---|---|
| Landing | guest/signed-in, truthful 12-lane/Play messaging, price, CTA/error |
| Wizard | draft/generating/AI error/denied/approved/stale approval, pending/paid/failed checkout |
| Readiness/dashboard | unknown/blocked/ready/running/needs_attention, ba progress và denominators |
| Lane detail | device/account changes, run-vs-step retry, expected/observed, missing/expired media |
| Report/operator | generating/failed/frozen/corrected, retention/download, replace/extend/cancel/quarantine |

Each state có role visibility, server source, primary/secondary action, loading/error copy EN/VI, keyboard focus và mobile layout. Không dùng mock badge “verified/paid/pass” mà thiếu label prototype/source semantics.

## 4. Bước làm
1. Build requirement-to-screen/state map và wireframes sử dụng component patterns repo.
2. Write interaction/data requirements cho FE/API teams; annotate source fields, unknown/recovery paths.
3. Prototype full customer/operator flows và conflict/error paths; accessibility review.
4. Người developer và operator thật làm tasks không được dẫn; ghi completion/time/misunderstanding/quote redacted.
5. Prioritize findings, sửa/retest các case hiểu nhầm price/Play/Blocked/pass; product ký spec version.

## 5. Acceptance
- [ ] AC1: state/role/next-action coverage tất cả screens trên.
- [ ] AC2: người dùng phân biệt service/app quality/Play evidence và pricing.
- [ ] AC3: blocker/missing/retry/cancel recovery có interaction spec.
- [ ] AC4: mobile/keyboard/EN/VI reviewed; findings có owner và disposition.

## 6. Test matrix
| ID | User task | Expected / evidence |
|---|---|---|
| 20a-T1 | Tìm giá trị/giá/CTA từ landing | Accurate explanation và đúng route intent |
| 20a-T2 | Scenario denied / readiness blocked | Tìm reason/next action/actor, không nghĩ app test Failed |
| 20a-T3 | 12 lanes, 168 runs, Play Unknown | Không suy 12 Google testers verified/Google approved |
| 20a-T4 | Operator replace/cancel; customer old retry image | Correct identity/history and action consequence |
| 20a-T5 | Keyboard/mobile/EN/VI full prototype | Focus/labels/errors readable; findings recorded |

## 7. Review và DoD
Product/UX review spec version, user participants test independently; QA checks state coverage. Store prototype link/screens, anonymized findings/task results and fixes. Failure→design revision→retest impacted cases. DONE needs AC1–4, real participant evidence; không thay implemented browser acceptance ở 08/14/19b.
