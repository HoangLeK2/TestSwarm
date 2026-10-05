# ADL-14 — Wizard production App/Scenario/Review/Payment/Readiness

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | FE + BE service API / product + security + QA |
| Dependencies | 02, 04, 09, 06, 13a; UX 20a, roles 15 |
| Deliverable | Durable full wizard, version/conflict handling, checkout/recovery E2E |

## 2. Source/gap
Existing campaign UI/client reusable; wizard dịch vụ chưa proven. `front-end/src/features/device-farm/services/generated/DeviceFarmApi.ts` phải generate từ canonical OpenAPI 00, không viết DTO khác backend.

## 3. State/contract
Draft data persisted theo org/campaign/revision. Steps App→Scenario→Review→Payment chỉ mở khi server state đủ; client page index không là quyền thực hiện mutation. Review references approved scenario hash/version, immutable package/price/retention/retest/refund policy snapshot. Edit App/Scenario invalidates dependent approval/review; paid order không tự overwrite package, cần explicit change policy.

Provider return page pending/paid/failed do server; chưa verified không readiness paid. Refresh/back/network uncertain state load server trước submit retry. Checklist readiness có blockers/owner/next action, clock chỉ start qua 06.

## 4. Bước làm
1. UX state diagram và conflict/error copy; contract draft revision và approval/order dependency.
2. App form package/link/goal/build test environment, inline server validation, save progress.
3. Scenario generate/approve review view; Review package/price/policy consent snapshot.
4. Provider checkout integration/return polling/resume; keyboard/mobile/EN/VI và aria error states.
5. Tests repeat submit/cross-org/edit-after-review/webhook delay; all generated client/typecheck/i18n checks.

## 5. Acceptance
- [ ] AC1: refresh/back giữ draft và revision conflict rõ.
- [ ] AC2: no checkout trước approval; review đúng version/price/policy.
- [ ] AC3: repeated submits không duplicate campaigns/order/charge.
- [ ] AC4: server controls payment/readiness state, no clock from redirect.
- [ ] AC5: cross-org deny và accessible responsive EN/VI.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 14-T1 | Full wizard sandbox E2E | Same campaign/order, verified state rồi checklist |
| 14-T2 | Refresh/back/offline submit retry | Draft retained; same idempotent intent |
| 14-T3 | Edit approved scenario while review tab open | Stale revision/approval rejected, review refreshed |
| 14-T4 | Deep-link Payment without approval hoặc success redirect only | Server reject/pending, no start |
| 14-T5 | Org B URL/API draft/order A | Denied, no leakage |
| 14-T6 | Keyboard/mobile/EN/VI errors/loading | Focus/labels actionable, no blocked blank screen |

## 7. Review và DoD
Product ký review policy copy, BE/security inspect mutations, QA replay T1–6 qua browser và direct API. Evidence version/order rows, recordings, commands/exit codes, schema/client diff. Fail → REWORK/rerun wizard checkpoints; DONE cần AC1–5, không coi mock walkthrough là implemented journey.
