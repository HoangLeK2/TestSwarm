---
title: "Campaign Scenario Repeat Config"
description: "Add per-selected-scenario run configuration so a campaign can execute each selected scenario once or multiple times in order."
status: completed
priority: P2
effort: 6h
branch: refacetor/stream-webrtc
tags: [feature, backend, frontend, database, api]
created: 2026-08-05
---

# Campaign Scenario Repeat Config

## Overview

Add per-selected-scenario run configuration in campaign setup/editing: each selected scenario defaults to 1 run, and can be set to repeat N times. Runtime expands the pinned scenario sequence, so campaign refs `[A, B, C]` with `B.repeat_count = 2` executes `A -> B -> B -> C`.

Do not duplicate scenario definitions. Store execution config on the campaign-to-scenario selection row.

## Current Code Shape

- Org campaign scenario selection is stored in `campaign_org_scenario_refs`.
- `CampaignOrgScenarioRef` currently stores `campaign_id`, `org_scenario_id`, `pinned_version`, and `order_index`.
- API shape only exposes `scenario_id` and `scenario_version`.
- Runtime resolves campaign refs in `services/campaign/scenario_sources.py`.
- `services/campaign/execution_runtime.py::build_sequence_steps()` converts refs into top-level `run_scenario` steps.
- Frontend edit dialog stores selected scenario IDs only, so it currently loses per-ref config.

## Decision

Use `repeat_count` on `campaign_org_scenario_refs`.

Why:

- It belongs to the selected scenario in a campaign, not the reusable scenario.
- Existing ordering/version pinning already live on the same join row.
- Runtime only needs to expand refs before building the top-level `run_scenario` sequence.
- Backward compatible: existing rows default to `1`.

Rejected options:

- Duplicate scenario refs in `scenario_refs` payload: conflicts with the unique `(campaign_id, org_scenario_id)` constraint and makes per-device variables ambiguous.
- Add repeat to scenario body: wrong ownership, because the same org scenario can be reused by many campaigns with different run configs.
- Implement a new Temporal loop layer: unnecessary. Existing top-level `run_scenario` sequence already models the execution order.

## Data Contract

Add:

```json
{
  "scenario_id": "B",
  "scenario_version": 3,
  "repeat_count": 2
}
```

Rules:

- `repeat_count` is integer.
- Default is `1`.
- Minimum is `1`.
- Recommended maximum is `20` initially, to avoid accidental huge campaigns. We can raise later if needed.
- Missing/null/invalid values are rejected at API boundary, not silently normalized except missing older payloads.

Runtime metadata per generated step should include:

```json
{
  "type": "run_scenario",
  "scenario_id": "B",
  "variables": { "...": "..." },
  "repeat_index": 0,
  "repeat_count": 2,
  "scenario_sequence_index": 1
}
```

Keep `SCENARIO_INDEX` as the expanded sequence index to preserve monitor/progress behavior. Add `SCENARIO_REF_INDEX`, `SCENARIO_REPEAT_INDEX`, and `SCENARIO_REPEAT_COUNT` only if useful for variables/debugging.

## Implementation Phases

### Phase 1 - Backend schema and persistence

Files:

- `/Users/hoangle/farm/device-farm/device_farm/db/models/org_scenario.py`
- `/Users/hoangle/farm/device-farm/device_farm/db/migrations/<new>_campaign_scenario_repeat_count.py`
- `/Users/hoangle/farm/device-farm/device_farm/api/schemas/campaign_entity.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/campaign/scenario_ref_resolver.py`
- `/Users/hoangle/farm/device-farm/device_farm/db/crud/campaign_entity.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/campaign/service.py`
- `/Users/hoangle/farm/device-farm/device_farm/api/routes/campaigns.py`

Tasks:

1. Add `repeat_count` column to `CampaignOrgScenarioRef`, nullable false, default `1`.
2. Create migration with `server_default='1'`, backfill existing rows, then keep non-null.
3. Add `repeat_count` to `CampaignScenarioRefIn` and `CampaignScenarioRefOut`.
4. Extend `ResolvedScenarioRef` and resolver validation.
5. Update `replace_campaign_scenario_refs()` to persist `(scenario_id, version, order, repeat_count)`.
6. Update `_refs_from_row()`, `_ref_views_from_resolved()`, and `_entity_out()` so list/detail APIs round-trip the value.
7. Keep create/update backward compatible when old clients omit `repeat_count`.

Acceptance:

- Existing campaign rows return `repeat_count: 1`.
- Creating/updating a campaign with `repeat_count: 2` persists and returns `2`.
- `repeat_count: 0`, negative, or too large returns validation error.

### Phase 2 - Runtime expansion

Files:

- `/Users/hoangle/farm/device-farm/device_farm/services/campaign/scenario_sources.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/campaign/execution_runtime.py`
- `/Users/hoangle/farm/device-farm/device_farm/temporal/workflows.py` only if progress display needs clearer expanded labels.

Tasks:

1. Include `repeat_count` in `org_scenario_refs_from_campaign()`.
2. Preserve repeat config through `resolve_campaign_scenario_refs()`.
3. Update `build_sequence_steps()` so each ref emits `repeat_count` run_scenario steps.
4. Keep registry building deduped by scenario ID; do not load scenario body multiple times.
5. Ensure scenario-scoped device vars still resolve by original `scenario_id`; repeated runs share same scoped vars.
6. Add step metadata for repeat index/count so monitor/debug logs can distinguish `B #1` and `B #2`.

Acceptance:

- A/B/C with B=2 yields exactly 4 top-level steps: A, B, B, C.
- Registry loads B once.
- Per-device scenario vars for B apply to both B runs.
- Campaign finalization still counts one execution per device, not per repeated scenario.

### Phase 3 - Frontend campaign configuration UI

Files:

- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/types.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/edit-campaign-entity-dialog.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/campaign-org-scenario-picker.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/create-campaign-dialog.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/campaign-list/CampaignScenarioSummary.tsx`
- `/Users/hoangle/farm/device-farm/front-end/messages/vi.json`
- `/Users/hoangle/farm/device-farm/front-end/messages/en.json`

Tasks:

1. Change selected state from `string[]` to `CampaignScenarioRefIn[]` where campaign editing needs config.
2. Keep picker ergonomics: checkbox/select scenario plus a compact number input or stepper for run count.
3. Default newly selected scenarios to `repeat_count: 1`.
4. Disable repeat controls when body is locked.
5. Submit `scenario_refs: [{ scenario_id, repeat_count }]`.
6. Show summary count based on expanded execution plan, for example `3 kịch bản -> 4 lượt chạy`.
7. Localize all labels in existing `campaignsFeature` namespaces.

Acceptance:

- User can set B to 2 from campaign create/edit.
- Reopening the campaign shows B still set to 2.
- Body-locked campaigns do not allow changing repeat counts.
- No broad React Query invalidation beyond the existing exact campaign list/detail refresh pattern.

### Phase 4 - Monitor/result visibility

Files:

- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/workflow-step-list.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/lib/workflow-step-list-model.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/campaign-monitor/workflow-progress-card.tsx`

Tasks:

1. Make repeated `run_scenario` rows distinguishable: `B (1/2)`, `B (2/2)`.
2. Ensure progress totals reflect expanded step count.
3. Avoid changing persisted execution semantics unless the existing event payload already carries enough metadata.

Acceptance:

- Monitor clearly shows `A -> B (1/2) -> B (2/2) -> C`.
- Existing single-run campaigns still display as before.

### Phase 5 - Tests and verification

Backend focused tests:

- Add/update tests around campaign create/update response round-trip.
- Add `build_sequence_steps()` unit test for A/B/C with B repeat 2.
- Add resolver validation tests for default, min, max, invalid.
- Add migration/backward compatibility check if migration tests exist.

Frontend focused tests:

- Add/update picker or dialog tests if existing harness covers it.
- Add utility-level test for expanded scenario summary if implemented as a helper.
- Run touched-file prettier/eslint.

Commands to run:

```bash
cd device_farm && pytest tests/test_epic04_campaign_entity.py tests/test_epic04_campaign_device_binding.py -q
cd device_farm && pytest tests/test_campaign_dispatch_n2n.py -q
cd front-end && pnpm exec prettier --check <touched-files>
cd front-end && pnpm exec eslint <touched-files>
git diff --check
```

Before committing:

- Run GitNexus `detect_changes()` if the MCP/CLI index is refreshed and available.
- If GitNexus remains stale, report that scope verification used source inspection plus focused tests instead.

## Edge Cases

- Existing campaigns: migration defaults refs to 1.
- Old clients: omitted `repeat_count` means 1.
- Duplicate selected scenario IDs remain unsupported because of the existing unique constraint. Repetition is represented by `repeat_count`.
- Recovery scenarios should not inherit campaign repeat config unless they are also selected as normal campaign refs.
- Start/resume from `start_step` may resume into an expanded sequence. This is acceptable, but tests should prove expanded ordering is stable.
- Very high repeat count can inflate Temporal workflow history and phone runtime. Cap initially.

## Rollout Plan

1. Ship DB/API/runtime behind backward-compatible defaults.
2. Ship UI controls after API is ready.
3. Verify on one campaign with three scenarios and one device.
4. Verify at least one repeated scenario with scenario-scoped device variables.
5. Rebuild/restart backend container before claiming runtime proof, because backend source changes may not be bind-mounted in this project.

## Open Decision

Recommended cap: `repeat_count <= 20`.

If campaign operators need larger loops, use an explicit scenario-level repeat node inside the scenario body, because that makes long loops visible where step-level automation is authored.
