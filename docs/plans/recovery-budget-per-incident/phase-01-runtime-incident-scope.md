# Phase 1 - Runtime Incident Scope

Status: Done
Priority: P1
Effort: 4h

## Objective

Change recovery attempt enforcement from run-wide step/rule counters to incident-scoped counters so repeated failures in loop iterations can each run recovery.

## Related Files

- `/Users/hoangle/farm/device-farm/device_farm/services/execution/recovery_runner.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/execution/step_runner.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/execution/recovery_policy.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/context.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/control_flow.py`
- `/Users/hoangle/farm/device-farm/device_farm/tests/test_incident_recovery_policy.py`

## Design

Introduce a stable recovery incident key for one failed step execution. The key should distinguish repeated executions of the same scenario node, including loop iterations and nested scenarios.

Recommended shape:

```text
{scenario_depth_or_path}:{step_index}:{monotonic_failure_counter}
```

The monotonic counter should live in `ScenarioContext.ctx`, for example `_recovery_incident_seq`. This keeps the implementation independent from the specific loop node type and works for normal steps, `loop`, `repeat`, nested `run_scenario`, and Temporal fallback paths.

## Runtime Rules

1. Create an incident key when a step execution first returns failure and enters `maybe_recover_step()`.
2. Reuse that key while handling retry attempts for the same failed execution.
3. Allocate a new key when the same step fails later as a separate loop iteration or separate step execution.
4. Keep `total_attempts` run-wide.
5. Enforce `max_attempts_per_step` by incident key plus step index, not by `step_index` alone.
6. Enforce `rule.max_attempts` by incident key plus rule id, not by `rule_id` alone.
7. Keep recovery sub-scenarios guarded by `_recovery_disabled=True`.

## Implementation Steps

1. Run GitNexus impact analysis on `maybe_recover_step`, `_budget_available`, `_record_attempt`, and `execute_step_with_retry`.
2. Add a helper in `recovery_runner.py` to resolve or create the current recovery incident key.
3. Update `_state()` to include `by_incident`, `by_incident_step`, and `by_incident_rule`.
4. Update `_budget_available()` to check global total plus incident-scoped counters.
5. Update `_record_attempt()` to increment the incident-scoped counters and keep old counters only for telemetry compatibility.
6. Ensure `retry_step` does not accidentally create a new incident key before the current incident budget has been applied.
7. Ensure pause/cancel checks remain before and after recovery scenario execution.

## Edge Cases

- Same node fails in 100 loop iterations: recovery can run 100 times unless `max_total_attempts` is reached.
- Recovery retries the same failed step and it fails immediately: this is still the same incident budget.
- Recovery scenario fails: record the attempt and apply configured `on_failure`.
- Recovery scenario itself hits a recoverable-looking error: do not recover recursively because `_recovery_disabled=True`.
- Campaign is paused or cancelled during recovery: stop quickly and return the existing pause/cancel result.

## Success Criteria

- A repeated loop failure is not blocked by stale `by_step[str(idx)]` or `by_rule[rule.id]` counters.
- A single unrecovered incident cannot spin forever.
- Existing recovery behavior for non-loop scenarios remains unchanged except for clearer budget semantics.

## Completed

- Added incident-scoped recovery counters.
- Preserved legacy counters as telemetry only.
- Reused the same incident key across recovery retries in one failed step execution.
- Added cancel handling after nested recovery returns.
- Inherited `_scenario_registry` into nested scenarios so loop bodies can resolve recovery playbooks.
