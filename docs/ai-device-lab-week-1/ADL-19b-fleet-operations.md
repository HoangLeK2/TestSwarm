# ADL-19b — Production fleet operations: replace, extend, cancel và expiry

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | BE fleet + FE operator / runtime/DB + billing + QA |
| Dependencies | 19a, 05, 07, 09; permissions 15 and participation 03b |
| Deliverable | Operator health/action UI, atomic replacement/history, extension/cancel/drain workers |

## 2. Source/gap
Existing device FSM/admin transfer/reset paths reusable, but no service lane replacement+policy/quota delta lifecycle. Do not rewrite historical serial in old executions or assume changing machine proves same Play account.

## 3. Contract
- Health sample timestamp/freshness, ready eligibility hygiene+reservation+runtime claim, owner and reason per blocker.
- Replacement transaction reserves new device before switches assignment, records old/new device interval/actor/reason; lane/tester_label constant, old run snapshot untouched. Active old run drain; no overlapping unsafe control.
- Account stays same only with observed account identity proof; account changed→new participation identity/continuity, not auto-carry days.
- Extension creates immutable policy delta/consent/order entitlement/quota/reservation update; added slots count separate from original 168. Report freeze stays unchanged, next version/extension report references previous.
- Cancel/expire stop future dispatch, signal/drain current runs, revoke job secrets, finalize quota/refund policy, hygiene/quarantine, release reservation **after** drain; idempotent recovery when components down.

## 4. Bước làm
1. Define command/state transition DTOs and concurrent replace/cancel behavior.
2. Implement atomic assignment intervals/replacement reservation and health UI with next actions.
3. Extension preview cost/quota/end date/reservations, consent+verified billing delta; no silent date rewrite.
4. Cancel/expiry durable cleanup saga with checkpoints/audit and outage retry.
5. Fault/race tests, operator browser demo and actual permitted device hygiene proof.

## 5. Acceptance
- [ ] AC1: replacement retains lane/history and no double booking/control.
- [ ] AC2: quarantine/dirty device excluded from reserve/dispatch.
- [ ] AC3: account/device changes handled independently with evidence.
- [ ] AC4: extension consent/policy/quota/billing immutable and traceable.
- [ ] AC5: cancel/expiry recovery drains/releases without losing history/leaking secret.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 19b-T1 | Offline→replace eligible device→resume | Same lane, new assignment history, old artifacts untouched |
| 19b-T2 | Concurrent replace/cancel or no spare capacity | Consistent winning command; no orphan reservations |
| 19b-T3 | Device changed then account changed | Correct distinct participation consequences |
| 19b-T4 | Extension paid/consented + frozen report exists | New delta/slots; old cutoff/checksum unchanged |
| 19b-T5 | Cancel active run; relay/storage outage during cleanup | Future jobs stop; durable retry, no premature reuse |
| 19b-T6 | Approved Device Target cleanup verification fails | quarantine; no reserve/dispatch until independent clean |

## 7. Review và DoD
Runtime/DB reviewer signs lifecycle, billing consent/delta, operator/QA device+browser evidence. Keep target type, before/after assignment/ledger, saga/audit logs, recordings. Fail → needs_attention/quarantine, REWORK/rerun race/cleanup. DONE needs AC1–5; expiry monitoring/recovery must be in 21 runbook.
