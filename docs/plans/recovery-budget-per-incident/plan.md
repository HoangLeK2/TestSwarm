---
title: "Recovery Budget Per Incident"
description: "Change recovery attempt accounting so recurring loop failures can run recovery on each new incident while preserving hard guards against unrecoverable loops."
status: implemented
priority: P1
effort: 8h
branch: fix/sse
tags: [bugfix, backend, frontend, execution, recovery]
created: 2026-06-19
---

# Recovery Budget Per Incident

## Overview

Current recovery accounting is run-wide for `step_index` and `rule_id`. That protects the device from infinite recovery, but it also means a long loop can stop recovering after the first one or two failures on the same node.

The desired behavior is:

- Each new failed step execution can trigger recovery again, even when it is the same scenario node inside a loop.
- The same unresolved incident is still capped by `rule.max_attempts` and `max_attempts_per_step`.
- `max_total_attempts` remains the global safety cap for the whole scenario run.
- Pause and cancel must interrupt recovery quickly.

## Current Evidence

- `device_farm/services/execution/recovery_runner.py` stores `_recovery_state.total_attempts`, `_recovery_state.by_step[str(idx)]`, and `_recovery_state.by_rule[rule.id]`.
- `device_farm/services/execution/step_runner.py` calls `maybe_recover_step()` only after a step returns failure.
- `retry_step` re-runs the failed step through normal step execution.
- Recovery sub-scenarios already run with `_recovery_disabled=True`, preventing recursive recovery.
- Loop handlers in `device_farm/tasks/scenario/steps/control_flow.py` reuse the same step indexes across iterations.

## Target Semantics

Example: one main scenario has a loop of 999999 iterations. Step `12` fails on iteration 1, recovery succeeds, and the main scenario continues. Step `12` fails again on iteration 20.

Expected result:

- Iteration 1 failure gets a recovery incident key and can run recovery.
- Iteration 20 failure gets a different recovery incident key and can run recovery again.
- If recovery retries step `12` and it immediately fails again for the same incident, the same incident budget applies.
- If `max_total_attempts` is reached, recovery stops and the step fails or follows the configured terminal outcome.

## Recommended Architecture

```text
failed step execution
  -> create or reuse recovery incident key
  -> match recovery rule
  -> check global total budget
  -> check per-incident step budget
  -> check per-incident rule budget
  -> run recovery scenario with recovery disabled
  -> retry/continue/fail according to recovery outcome
```

## Budget Model

Replace run-wide step/rule counters for enforcement with incident-scoped counters:

```json
{
  "total_attempts": 12,
  "by_incident": {
    "root:12:37": 1
  },
  "by_incident_step": {
    "root:12:37:12": 1
  },
  "by_incident_rule": {
    "root:12:37:fb-popup": 1
  },
  "last_incident": {
    "key": "root:12:37",
    "type": "facebook_popup",
    "rule_id": "fb-popup"
  }
}
```

Keep old keys such as `by_step` and `by_rule` as best-effort telemetry during the migration if existing monitor code reads them, but do not use them as the primary blocker for loop recovery.

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Runtime Incident Scope | Done | 4h | [phase-01-runtime-incident-scope.md](./phase-01-runtime-incident-scope.md) |
| 2 | Policy And UI Semantics | Done | 2h | [phase-02-policy-and-ui-semantics.md](./phase-02-policy-and-ui-semantics.md) |
| 3 | Verification And Rollout | Done | 2h | [phase-03-verification-and-rollout.md](./phase-03-verification-and-rollout.md) |

## Implementation Notes

- Recovery attempt enforcement now uses incident-scoped counters: `by_incident`, `by_incident_step`, and `by_incident_rule`.
- Legacy `by_step` and `by_rule` counters remain as telemetry but no longer block new loop incidents.
- `step_runner` reuses one incident key across `retry_step` recovery retries in the same failed step execution, so the same unresolved incident is still capped.
- A later loop iteration or separate step execution receives a new incident key and can recover again until `max_total_attempts` is reached.
- Recovery cancellation is rechecked after nested recovery returns, so user cancel is reported as `cancelled` instead of `incident_recovery_failed`.
- Recovery events now carry `incident_key` and `attempt` for monitor/debugging.
- Nested scenarios now inherit `_scenario_registry`, so recovery can resolve playbooks inside loop/repeat/run_scenario child executions.
- Frontend recovery policy editing preserves and exposes `max_total_attempts` and `max_attempts_per_step`.

## Non-Goals

- Do not make recovery run before every step.
- Do not allow recovery scenarios to recursively trigger recovery.
- Do not remove the global `max_total_attempts` safety cap.
- Do not move recovery execution into `agent-boot`.
- Do not change scenario node ordering or campaign scheduling semantics.

## Required GitNexus Gate

Before implementation edits any function, class, or method, run GitNexus impact analysis for that symbol and record direct callers, affected processes, and risk. If GitNexus is unavailable or stale, run `npx gitnexus analyze` first or explicitly document the fallback.

## Validation Commands

```bash
cd /Users/hoangle/farm/device-farm
uv run --project device_farm pytest device_farm/tests/test_incident_recovery_policy.py
uv run --project device_farm pytest device_farm/tasks/scenario/tests/test_action_cancel.py device_farm/tests/test_execution_cancel_flags.py
uv run --project device_farm python -m py_compile device_farm/services/execution/recovery_runner.py device_farm/services/execution/step_runner.py device_farm/services/execution/recovery_policy.py

cd /Users/hoangle/farm/device-farm/front-end
pnpm test -- recovery-policy-editor-model
pnpm exec tsc --noEmit
```

Actual validation:

```bash
uv run --project device_farm python -m py_compile device_farm/services/execution/recovery_runner.py device_farm/services/execution/step_runner.py device_farm/services/execution/recovery_policy.py device_farm/tasks/scenario/executor.py device_farm/tasks/scenario/tests/test_executor.py
uv run --project device_farm pytest device_farm/tests/test_incident_recovery_policy.py device_farm/tests/test_epic04_temporal_step_retry.py device_farm/tasks/scenario/tests/test_executor.py device_farm/tasks/scenario/tests/test_action_cancel.py device_farm/tests/test_execution_cancel_flags.py
pnpm --dir front-end exec node --experimental-strip-types --test src/features/campaigns/lib/recovery-policy-editor-model.test.ts
pnpm --dir front-end exec eslint src/features/campaigns/lib/recovery-policy-editor-model.ts src/features/campaigns/components/recovery-policy-editor.tsx src/features/campaigns/types.ts
git diff --check -- device_farm/services/execution/recovery_runner.py device_farm/services/execution/step_runner.py device_farm/services/execution/recovery_policy.py device_farm/tasks/scenario/executor.py device_farm/tests/test_incident_recovery_policy.py device_farm/tests/test_epic04_temporal_step_retry.py device_farm/tasks/scenario/tests/test_executor.py front-end/src/features/campaigns/types.ts front-end/src/features/campaigns/lib/recovery-policy-editor-model.ts front-end/src/features/campaigns/lib/recovery-policy-editor-model.test.ts front-end/src/features/campaigns/components/recovery-policy-editor.tsx front-end/messages/vi.json front-end/messages/en.json docs/plans/recovery-budget-per-incident
```

GitNexus notes:

- `execute_step_with_retry` impact: LOW, 4 direct callers, Execution module.
- `run_nested_scenario` impact: HIGH, 4 direct callers and 23 impacted symbols. Change was limited to inheriting `_scenario_registry` into child scenarios.
- Recovery symbols were not present in the index before implementation because the recovery files were untracked.
- `npx gitnexus analyze` and `npx gitnexus detect-changes` later failed with `lbug.wal without lbug.shadow`, so final detect-changes could not complete.

## Handoff

Run:

```bash
/ck:cook --auto /Users/hoangle/farm/device-farm/docs/plans/recovery-budget-per-incident/plan.md
```
