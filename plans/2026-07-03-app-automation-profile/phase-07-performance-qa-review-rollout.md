# Phase 07: Performance, QA, Review, Rollout

## Overview

Run final quality gates before enabling the feature broadly.

## Performance Plan

- Benchmark hierarchy dump path.
- Benchmark locator scoring on cached and fresh hierarchy.
- Benchmark watcher overhead across action-heavy scenarios.
- Record p50/p95 for:
  - action without watcher
  - action with watcher no-op
  - selector miss with watcher retry
  - semantic locator fallback

## Test Matrix

- Unit: schemas, selector scoring, watcher matching, state machines.
- Integration: scenario executor, account resolution, monitor event payload.
- Frontend: step editor, defaults, monitor rendering.
- E2E: Playwright for editor/monitor UI.
- Live device: at least 3 app shapes:
  - normal resourceId login
  - no-resourceId form
  - popup/update dialog interruption

## Required Commands

- Targeted backend pytest for changed modules.
- Targeted frontend tests/lint for touched files.
- `git diff --check`
- GitNexus `detect_changes({scope: "compare", base_ref: "main"})` before commit/PR.

## Subagent Review Gates

- `reviewer`: correctness and maintainability.
- `performance-reviewer`: p95 regression and hierarchy cache strategy.
- `security-reviewer`: credential redaction, watcher safety, authorization.
- `qa-agent`: final test evidence and manual smoke summary.

## Rollout Strategy

1. Feature flag off by default.
2. Enable for one internal org/device.
3. Run shadow mode watcher logging without auto-click for risky apps.
4. Enable auto-click only for approved watcher profiles.
5. Expand to campaign flows after monitor evidence is stable.

## Success Criteria

- No measurable regression on existing tap/select flows.
- New flows produce clear artifacts.
- Rollback is one flag/config change.
- Reviewers sign off on correctness, security, performance, and QA evidence.

## Implementation Progress

- Targeted backend tests pass for profile validation, locator scoring, watcher evaluation, runtime step handlers, and pre-step watcher hook integration.
- Targeted frontend tests pass for app automation node shells, profile editor model mutations, and SSE monitor detail folding.
- Frontend `next build --no-lint` passes after structured editor and monitor rendering changes.
- Python compile, trailing whitespace scan, and `git diff --check` pass for touched files.
- Existing executor/retry/capture regression tests pass for the touched `step_runner` path.
- Full frontend/backend suite, live-device smoke, formal p50/p95 benchmark, monitor route checks, and rollout flagging remain pending.
