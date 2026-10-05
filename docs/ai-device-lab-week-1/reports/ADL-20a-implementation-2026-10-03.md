# ADL-20a implementation evidence — 2026-10-03 (finalized 2026-10-04)

## Status and scope

- Local implementation status: **READY_FOR_REVIEW**.
- Plan task status remains unchanged. ADL-20a cannot be marked DONE until product/UX, developer participant, operator, accessibility reviewer, and real participant evidence required by the plan are recorded.
- Implementation is a side-effect-free prototype at `/en/ai-device-lab` and `/vi/ai-device-lab`. It does not call payment, device, campaign, or operator APIs.
- Baseline: branch `fix/bug-ui-node`, HEAD `1a50ede6`.

## Implementation map

| Plan surface | Prototype evidence |
|---|---|
| Landing | Guest/signed-in/CTA-error fixtures, package scope, 12 logical lanes, 14 service days, 168 scheduled slots, pricing decision pending, explicit prototype disclosure |
| App → Scenario → Review → Payment → Readiness | Clickable wizard with generating/AI-error/denied/approved/stale scenario, immutable package snapshot, pending/failed/paid payment, and unknown/blocked/ready/running/needs-attention readiness |
| Dashboard | Service progress, app-quality progress, and account-specific Play participation shown as separate axes |
| Lane detail | Stable lane identity, device/build/attempt lineage, retry history, and explicit expired evidence |
| Report | Generating/failed/frozen/corrected transitions, frozen cutoff, complete counts, missing-evidence disclosure, and correction lineage |
| Operator | Replacement, cancellation, extension, and quarantine consequence previews without external side effects |
| State map | 31 interactive fixtures, each with role, locale-neutral server source, primary/secondary actions, and EN/VI loading/error copy |

Reusable implementation units are kept under `front-end/src/features/ai-device-lab-prototype/`: typed localized copy, a typed state catalog, and the composed prototype view. The public route only resolves locale and delegates to the feature.

## Acceptance and E2E evidence

| Acceptance | Automated evidence | Result |
|---|---|---|
| AC1 — state/role/next-action coverage | `20a-AC1` checks all 31 named states, opens every interactive fixture, and requires non-empty role/source/primary/secondary/loading/error fields | AUTO_TEST_PASS / ACCEPTANCE_PENDING_REVIEW |
| AC2 — distinguish service/app quality/Play evidence and pricing | `20a-T1` verifies route, package, server-owned pricing note, CTA error/retry and wizard; `20a-T3` verifies three distinct progress axes and rejects “Google approved” wording | AUTO_TEST_PASS / ACCEPTANCE_PENDING_REVIEW |
| AC3 — blocker/missing/retry/cancel recovery | `20a-T2` verifies generation failure/stale/denied scenario plus Blocked/Unknown/Running readiness controls; `20a-T4` verifies run/step retry lineage, expired evidence, replacement/cancellation consequences, and report failure/correction provenance | AUTO_TEST_PASS / ACCEPTANCE_PENDING_REVIEW |
| AC4 — mobile/keyboard/EN/VI review | `20a-T5` drives the full wizard and every top-level view in both VI and EN at 390×844, uses Tab/Shift+Tab for the wizard, verifies heading focus and checks overflow after every view; automated accessibility behavior passes, while human accessibility review remains pending | AUTO_TEST_PASS / ACCEPTANCE_PENDING_REVIEW |

The E2E suite runs real Chromium against a real local Next.js server through Playwright. Latest result: **6/6 passed in 21.7 seconds**.

Latest mobile development-server measurement from `20a-T5`:

```json
{
  "domNodes": 454,
  "navigationMs": 3496.6,
  "transferBytes": 6293716,
  "hasHorizontalOverflow": false
}
```

The timing and transfer values are the maximum of the EN and VI navigation samples. These numbers are a regression budget for the local development build, not a production load-test or device-lab SLA. Production build output for `/[locale]/ai-device-lab` is 22.3 kB route size and 133 kB First Load JS.

## Automated review findings and disposition

| Finding | Owner | Disposition / retest |
|---|---|---|
| Required states were static rather than clickable | UX/FE | Fixed with per-screen transitions and 31 interactive state fixtures; `20a-T1/T2/T4/AC1` pass |
| Vietnamese route leaked English visible/accessible copy | UX/FE | Localized component copy and converted server sources to locale-neutral identifiers; `20a-T5` pass |
| State contract lacked secondary/loading/error fields | UX/FE + API design | Added typed fields, rendered them, and asserted every row; `20a-AC1` pass |
| Active controls and view transitions lacked accessible state/focus semantics | UX/FE | Added `aria-current`, `aria-pressed`, heading focus management, and keyboard traversal; `20a-T5` pass |
| Recheck readiness could bypass unresolved blockers | UX/FE | Recheck preserves Blocked/Unknown, Ready alone enables Start, and Running exposes only Open dashboard; `20a-T2` pass |
| Ready/Running badges conflicted with unresolved blocker instructions | UX/FE | Ready/Running render fresh resolved evidence and remove blocker instructions; `20a-T2` pass |
| Ready → Start unmounted the focused control without announcing Running | UX/FE + QA | Running focuses its new heading, and `20a-T2` activates Start from the keyboard and asserts the focus transition |
| State-fixture buttons were indistinguishable to screen readers and updated an off-screen preview | UX/FE | Added state-specific accessible names and moves focus to the updated preview; `20a-AC1` pass |
| State secondary/loading/error copy was generic | UX/FE + API design | Added an explicit EN/VI interaction contract for every state; `20a-AC1` pass |
| T5 covered only one full locale and used programmatic focus | QA | Parameterized the full EN/VI journey, added natural Tab/Shift+Tab traversal, and checks overflow on every view; `20a-T5` pass |
| Initial E2E assertions and report wording overstated acceptance | QA | Expanded T1–T5/AC1 and changed results to `AUTO_TEST_PASS / ACCEPTANCE_PENDING_REVIEW` |

## Verification commands

| Command | Result |
|---|---|
| `pnpm test:e2e:ai-device-lab` | PASS — 6 tests |
| `pnpm typecheck` | PASS |
| targeted `eslint` for route, feature, Playwright config, and E2E | PASS — zero warnings |
| `pnpm exec next build` | PASS; repository-wide pre-existing warnings remain |
| `pnpm audit --prod --json` | FAIL baseline — 193 advisories: 11 low, 90 moderate, 90 high, 2 critical |
| `gitnexus impact AiDeviceLabPage --direction upstream` | LOW — 0 upstream callers, 0 affected processes |
| `gitnexus impact AiDeviceLabPrototype --direction upstream` | LOW — 1 direct caller (the new route), 0 affected processes |
| `gitnexus detect-changes --scope all` | HIGH for the whole dirty worktree: 146 files, 211 symbols, 12 existing flows; this includes extensive unrelated user changes outside ADL-20a |

Playwright was pinned to 1.55.1 after the audit identified the advisory in 1.55.0; the final audit contains no Playwright advisory. The two remaining critical advisories resolve through the existing Next.js 15.5.9 dependency and need a separate platform upgrade with regression testing.

## Review gates still open

- Product must approve amount, currency, refund/cancellation policy, and server-owned price presentation before checkout can become real.
- Product/UX, developer participant, operator, accessibility reviewer, and real participants must review independently; anonymized findings need owner and disposition.
- Backend/payment/device/operator contracts and deployed/live-device proof are outside this prototype task.
- The existing dirty worktree was preserved; no commit, push, deployment, or external mutation was performed.
