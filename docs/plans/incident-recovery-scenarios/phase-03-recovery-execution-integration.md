# Phase 3 - Recovery Execution Integration

Status: Pending
Priority: P1
Effort: 6h

## Objective

Run user-configured recovery scenarios safely at step boundaries, preserve main-flow context, and decide the next action.

## Related Files

- `/Users/hoangle/farm/device-farm/device_farm/services/execution/recovery_policy.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/execution/recovery_runner.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/execution/step_runner.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/executor.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/composition.py`
- `/Users/hoangle/farm/device-farm/device_farm/temporal/activities.py`
- `/Users/hoangle/farm/device-farm/device_farm/temporal/workflows.py`
- `/Users/hoangle/farm/device-farm/device_farm/temporal/shared.py`

## Runtime Flow

1. Before sensitive step or after failure, collect incident candidates.
2. Match first enabled policy rule by incident type and attempts budget.
3. Emit `incident.detected`.
4. Run recovery scenario with same device, same execution id, same `_scenario_registry`, same variable context, and same `ctx`.
5. Run success checks.
6. Emit `incident.resolved` or `incident.failed`.
7. Apply outcome:
   - `retry_step`: rerun current step once through normal retry accounting.
   - `continue`: mark recovery handled and proceed.
   - `fail`: fail current step.
   - `pause_for_takeover`: mark execution paused with operator-visible reason.
   - `open_dlq`: fail with DLQ-friendly reason.

## Attempt Accounting

Store per-run counters in `ScenarioContext.ctx["_recovery_state"]`:

```json
{
  "total_attempts": 2,
  "by_step": {"12": 1},
  "by_rule": {"fb-popup": 2},
  "last_incident": {"type": "facebook_popup", "rule_id": "fb-popup"}
}
```

This state must be included in Temporal `StepsInput.context` and fallback runtime context so continue-as-new and nested scenarios do not reset budgets.

## Temporal Integration

MVP option:

- When recovery policy is enabled, force `batch_size=1` unless `execute_device_action_batch` grows an internal recovery hook.
- Preferred implementation: add recovery hook inside `execute_device_action_batch` after each step result, because batching is already where mini-scenario execution happens.
- Either way, do not let a failed step return to workflow before recovery attempt is recorded.

## Recovery Sub-Scenario Rules

- Recovery scenario may use existing steps: tap, key, wait, dismiss_popup, run_scenario.
- Recovery scenario cannot recursively trigger another recovery in MVP.
- Recovery scenario inherits variables but writes to same `ctx` only through normal steps.
- Recovery scenario failures are reported separately from the original incident.

## Implementation Steps

1. Add policy parser and matcher in `services/execution/recovery_policy.py`.
2. Add `RecoveryRunner` that wraps `run_nested_scenario`.
3. Add recovery-disabled flag when running a recovery scenario.
4. Hook fallback `ScenarioExecutor` after step failure and before sensitive steps.
5. Hook Temporal activity batch path after each mini-scenario result.
6. Preserve context and attempt counters across `StepsInput.context`.
7. Convert terminal outcomes to existing pause/DLQ/failure paths.

## Tests

- Fallback executor runs recovery scenario after detected popup and retries original step.
- Recovery attempt budget prevents infinite loop.
- Recovery scenario does not recursively trigger itself.
- Temporal batch path handles failure, recovery success, then retry.
- `batch_size=10` campaign with recovery enabled does not skip incidents.
- Cancel/pause flags still interrupt recovery.

## Success Criteria

- Popup/profile/stuck incidents can run user-selected recovery playbooks.
- Main crawl context, including active comment parent, survives recovery.
- Infinite recovery loops are impossible by policy and call-stack guard.
