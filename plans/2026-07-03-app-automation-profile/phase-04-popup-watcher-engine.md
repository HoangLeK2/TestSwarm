# Phase 04: Popup Watcher Engine

## Overview

Add a safe watcher layer that runs around scenario actions to dismiss known interruptions.

## Behavior

- Run before each action.
- Run after screen-changing actions.
- Run on selector miss before final retry.
- Scope watcher by package/activity/screen condition.
- Count triggers per run and enforce cooldown.

## Safety Rules

- No global `OK` click watcher.
- No payment/delete/purchase/permission watcher by default.
- Every watcher action must be logged.
- Watcher can be disabled per run.
- Watcher must stop after max trigger count.

## Expected Files

- Backend watcher matcher/executor.
- Scenario step result payload extension for watcher events.
- Tests for watcher conditions and guardrails.

## Tests

- Update dialog dismissed when matching package and text.
- Watcher does nothing outside package scope.
- Watcher respects cooldown and max triggers.
- Dangerous action text is rejected or requires explicit unsafe flag.
- Selector miss invokes watcher then retries once.

## Performance Gate

- Watcher loop must reuse hierarchy where possible.
- No repeated full hierarchy dump if current action already captured XML recently.
- Timing fields must show watcher overhead.

## Review Gate

- `security-reviewer`: accidental dangerous click risk.
- `qa-agent`: popup/ad/update dialog scenario matrix.

## Success Criteria

- Common popup/update/ad blockers stop breaking normal flows.
- Watcher behavior is visible in monitor and step artifacts.

## Implementation Progress

- Added isolated watcher evaluator in `device_farm/services/app_automation_watcher.py`.
- Watcher evaluator filters disabled/out-of-package/cooldown-blocked watchers before parsing hierarchy.
- Watcher state is keyed by effective package and watcher name.
- Default evaluation emits at most one trigger to avoid action storms.
- Added pre-step executor hook in `services/execution/step_runner.py`; it only runs when the step or scenario has `app_automation_profile.popup_watchers`.
- Added runtime glue in `tasks/scenario/app_automation_watchers.py` for `tap_text`, `tap_text_any`, `press_key`, and `noop` actions.
- Watcher hook stores cooldown/count state in `sc.ctx["_app_popup_watcher_state"]`, avoiding changes to `ScenarioContext`.
- Watcher events are attached to `step_result["app_popup_watchers"]`.
- Dedicated monitor rendering remains pending.
- Safety guardrails reject payment/delete/purchase-style watcher actions unless explicitly marked unsafe.
