---
title: "Incident Recovery Scenarios"
description: "Add campaign-level recovery playbooks that run user-configured scenarios when crawl execution detects popups, lost screen state, profile misnavigation, or stuck UI."
status: implemented
priority: P1
effort: 22h
branch: fix/sse
tags: [feature, backend, frontend, scenario, execution, recovery]
created: 2026-06-17
---

# Incident Recovery Scenarios

## Overview

Add a first-class recovery layer around scenario execution. Users configure recovery rules on a campaign. When execution detects an incident, the runtime pauses the current step boundary, runs the configured recovery scenario as a sub-scenario, verifies the expected screen state, then resumes, retries, skips, fails, opens DLQ, or waits for takeover.

This is not a new main-flow node. Recovery scenarios are normal org scenarios marked for recovery use and attached through campaign-level policy.

## Current Evidence

- `run_scenario` already executes nested org scenarios through `_scenario_registry`.
- Temporal batches leaf steps in `execute_device_action_batch`; recovery must hook there or batch must be disabled when recovery is active.
- Existing `dismiss_popup` is a fixed helper, not user-configurable incident handling.
- `execution_events` and SSE already support durable monitor timelines, but only `step.*` and `execution.*` event families exist.
- Facebook crawl correctness depends on context such as `_active_comment_parent_*`; recovery must preserve `ScenarioContext.ctx`.

## Non-Goals

- Do not move full scenario execution into `agent-boot`.
- Do not auto-solve login checkpoint, CAPTCHA, identity verification, or password-change screens.
- Do not add recovery as a manual node inside every crawl flow.
- Do not run recovery concurrently with an in-flight device action.
- Do not cap explicit deep crawl budgets such as 500 comments.

## Recommended Architecture

```text
Campaign recovery_policy
  -> dispatch prepares ScenarioInput.scenario_config.recovery_policy
  -> step execution boundary
       -> incident detector snapshot
       -> rule match
       -> emit incident.detected
       -> run configured recovery org scenario
       -> post-check
       -> emit incident.resolved / incident.failed
       -> retry/resume/skip/fail/DLQ
```

## Recovery Policy Shape

Store as a first-class JSON field on campaigns, with API schemas and generated frontend types:

```json
{
  "enabled": true,
  "max_total_attempts": 8,
  "max_attempts_per_step": 2,
  "rules": [
    {
      "id": "fb-popup",
      "incident_types": ["facebook_popup", "app_popup"],
      "scenario_id": "org-scenario-id",
      "max_attempts": 2,
      "trigger": "before_step_or_after_failure",
      "success_checks": [{"type": "not_incident", "incident_type": "facebook_popup"}],
      "on_success": "retry_step",
      "on_failure": "pause_for_takeover"
    }
  ]
}
```

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Contract And Storage | Done | 4h | [phase-01-contract-storage.md](./phase-01-contract-storage.md) |
| 2 | Incident Detection Runtime | Done | 5h | [phase-02-incident-detection-runtime.md](./phase-02-incident-detection-runtime.md) |
| 3 | Recovery Execution Integration | Done | 6h | [phase-03-recovery-execution-integration.md](./phase-03-recovery-execution-integration.md) |
| 4 | UI And Monitor | Done | 5h | [phase-04-ui-and-monitor.md](./phase-04-ui-and-monitor.md) |
| 5 | Tests And Rollout | Done | 2h | [phase-05-tests-and-rollout.md](./phase-05-tests-and-rollout.md) |

## Implementation Notes

- Added `campaigns.recovery_policy` JSON storage, API schema fields, service validation, frontend campaign create/edit controls, and a recovery policy entry in Control & Record when opened from a campaign.
- Runtime now carries `recovery_policy` through `ScenarioInput.scenario_config`, detects incidents after failed steps, prioritizes user-configured rule matchers (`match.text_any`, `match.result_any`, step/strategy/package/activity matchers), runs configured org scenarios as nested recovery scenarios, emits `incident.*` events, and can retry/continue/fail the main step. Hardcoded text heuristics are fallback only for rules without custom matchers.
- Monitor folds `incident.*` SSE events into the owning step row so recovery attempts are visible without adding scenario graph nodes.
- MVP limitation: `pause_for_takeover` and `open_dlq` are accepted policy outcomes but currently resolve to a failure message from the recovery layer; they do not yet open an interactive takeover session or create a DLQ entry directly.

## Required GitNexus Gate

Before implementation edits any function, class, or method, run GitNexus impact analysis for that symbol and record direct callers, affected processes, and risk. If GitNexus is unavailable, run `npx gitnexus analyze` first or explicitly document the fallback.

## Validation Commands

```bash
cd /Users/hoangle/farm/device-farm/device_farm
uv run pytest tests/test_temporal_workflows.py tests/test_epic04_execution_runtime.py
uv run pytest tasks/scenario/tests/test_executor.py tasks/scenario/tests/test_wait_cancel.py
uv run python -m py_compile temporal/shared.py temporal/activities.py temporal/workflows.py tasks/scenario/executor.py services/execution/activity_events.py

cd /Users/hoangle/farm/device-farm/front-end
pnpm test -- execution-event-utils step-retry-policy
pnpm exec tsc --noEmit
```

## Open Decisions

- First release should support only `retry_step`, `continue`, `fail`, `pause_for_takeover`, and `open_dlq`.
- Use org-scenario tag `recovery` for filtering; do not add a new `ScenarioKind` enum in MVP.
- Add a real `campaigns.recovery_policy` JSON column instead of hiding policy under campaign variables.
- Recovery event UI belongs in campaign monitor first; editor polish can follow once runtime behavior is proven.

## Handoff

Run:

```bash
/ck:cook /Users/hoangle/farm/device-farm/docs/plans/incident-recovery-scenarios/plan.md
```
