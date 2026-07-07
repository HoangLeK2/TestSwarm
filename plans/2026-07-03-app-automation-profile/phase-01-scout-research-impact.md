# Phase 01: Scout, Research, Impact Map

## Overview

Build the evidence map before implementation. No code changes in this phase.

## Objectives

- Map current selector, tap, hierarchy, popup dismiss, scenario step, monitor, and account value paths.
- Confirm where profile contracts should enter the system.
- Identify high-risk symbols and execution flows before any edits.
- Produce subagent reports for implementation phases.

## Required Subagents

- `explorer`: map current code paths and file ownership.
- `docs-researcher`: summarize LAMDA concepts worth copying: watcher, selector chain, OCR/image fallback, traceable remote inspection.
- `reviewer`: challenge scope and remove unnecessary features.

## Commands / Tools

- GitNexus `query({query: "scenario selector tap popup dismiss hierarchy"})`
- GitNexus `context({name: "_retry_find_element"})`
- GitNexus `context({name: "resolve_step_selector_fields"})`
- GitNexus `context({name: "_auto_dismiss_popup"})`
- GitNexus `query({query: "campaign monitor step event output"})`
- `rg` only for follow-up once GitNexus points to files.

## Files To Inspect

- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/utils.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/interaction.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/scenario_selector.py`
- `/Users/hoangle/farm/device-farm/device_farm/api/schemas/scenario.py`
- `/Users/hoangle/farm/device-farm/device_farm/common/scenario_schema.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/execution/activity_events.py`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/scenario-steps/types.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/scenario-steps/step-detail-panel.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/workflow-step-list.tsx`

## Deliverables

- Subagent scout completed in-thread: selector/tap/hierarchy, schema, monitor, and frontend seams mapped.
- LAMDA pattern review completed earlier: copied concepts only, no runtime dependency.
- Risk register started: schema/monitor unions, global popup dismiss, hierarchy parse overhead, watcher action safety.

## Success Criteria

- Completed: initial seams known before edits.
- Completed: dirty worktree and stale GitNexus index called out.
- Completed: decision made to add generic profile layer first, isolated from existing runtime.

## Risk

- Risk: over-copying LAMDA and bloating repo.
- Mitigation: keep LAMDA as pattern source only; no runtime dependency.
