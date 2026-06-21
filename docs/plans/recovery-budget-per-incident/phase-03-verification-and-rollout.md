# Phase 3 - Verification And Rollout

Status: Done
Priority: P1
Effort: 2h

## Objective

Prove that repeated loop incidents recover repeatedly, unrecoverable incidents are capped, and pause/cancel remains fast.

## Test Plan

Add or update tests around the smallest runtime seams:

1. Different incident keys with the same `step_index` and `rule_id` should each pass budget checks.
2. The same incident key and same rule should stop at `rule.max_attempts`.
3. The same incident key and same step should stop at `max_attempts_per_step`.
4. `max_total_attempts` should stop recovery across all incidents.
5. A loop simulation should fail the same nested step across multiple iterations and assert the recovery scenario is called once per failed iteration.
6. A recovery scenario should not trigger another recovery because `_recovery_disabled=True`.
7. Pause/cancel flags should interrupt before starting a new recovery attempt and before retrying the original step.

## Suggested Commands

```bash
cd /Users/hoangle/farm/device-farm
uv run --project device_farm pytest device_farm/tests/test_incident_recovery_policy.py
uv run --project device_farm pytest device_farm/tasks/scenario/tests/test_action_cancel.py device_farm/tests/test_execution_cancel_flags.py
uv run --project device_farm python -m py_compile device_farm/services/execution/recovery_runner.py device_farm/services/execution/step_runner.py device_farm/services/execution/recovery_policy.py

cd /Users/hoangle/farm/device-farm/front-end
pnpm test -- recovery-policy-editor-model
pnpm exec tsc --noEmit
```

## Manual Verification Scenario

Create a main scenario with a small loop, for example 5 iterations. Make the same node fail in iterations 1, 3, and 5 and attach a recovery scenario with `rule.max_attempts=1`.

Expected monitor result:

- Three `incident.detected` events.
- Three recovery attempts.
- No budget block from the repeated step index.
- If `max_total_attempts=2`, the third incident is blocked by the global cap.

## Rollout Notes

- Existing saved policies may still have low `max_total_attempts`; migration is not required, but release notes should tell operators to raise it for long loops.
- If monitor output currently shows run-wide `by_step` or `by_rule`, either keep those as telemetry or add incident-key fields before removing them.
- Do not claim performance gains from this change. The goal is correctness plus fast pause/cancel behavior, not lower per-step latency.

## Success Criteria

- Tests demonstrate loop recovery happens per failed occurrence.
- Tests demonstrate hard caps still stop infinite recovery.
- Frontend and backend agree on policy limits and labels.
- The implementation can be safely handed off to `/ck:cook`.

## Completed

- Added tests for new incidents on the same step/rule, same-incident caps, global caps, legacy telemetry counters, event incident keys, policy clamps, recovery retry key reuse, cancel during recovery, and real loop integration through nested `ScenarioExecutor`.
- Ran backend targeted pytest, frontend model tests, scoped ESLint, py_compile, and scoped diff-check.
- Full frontend `tsc --noEmit` remains blocked by pre-existing `.next/types` and test import/type errors outside this change.
