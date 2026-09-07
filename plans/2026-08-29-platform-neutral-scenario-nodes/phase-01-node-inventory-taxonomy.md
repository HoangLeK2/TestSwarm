# Phase 01 - Node Inventory And Taxonomy

## Goal

Classify every scenario node before changing labels or runtime behavior.

## Files To Inspect

- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/scenario-steps/types.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/flow-editor/step-detail-panel.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/flow-editor/platform-aware-steps.ts`
- `/Users/hoangle/farm/device-farm/device_farm/common/scenario_schema.py`
- `/Users/hoangle/farm/device-farm/device_farm/api/schemas/scenario.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/__init__.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/social_ext/contract.py`
- `/Users/hoangle/farm/device-farm/device_farm/db/seeds/scenario_templates.py`

## Taxonomy

- `core.device`: launch app, stop app, clear app, install apk, adb shell.
- `core.input`: tap, swipe, input, key, clipboard.
- `core.assert`: wait element, assert element, verify screen, assert app state.
- `core.extract`: OCR, hierarchy, screen data, generic entity extraction.
- `core.control`: loop, repeat, if, random pick, run scenario.
- `social.capability`: open comments, scan content, interact content, select target, connection action, community membership.
- `platform.adapter`: platform-only helpers, selectors, labels, tabs, package names.
- `platform.facet`: reusable platform-specific trait such as friend-request connection, follow connection, group community, page surface, comment overlay.
- `legacy.platform_named`: retired or migration-only node names.

## Implementation Steps

1. Create a generated or hand-maintained inventory report.
2. Mark each node with `scope`, `requires_platform`, `generic_recipe_available`, `adapter_required`, `facets`, `legacy`.
3. Identify nodes whose labels mention Facebook while type is neutral.
4. Identify neutral names with Facebook-only semantics.
5. Do not rename or remove anything in this phase.

## Acceptance

- Every node in `ALL_STEP_TYPES` has a taxonomy row.
- Every backend schema step type has a taxonomy row.
- All platform-named public step types are either absent or listed under migration-only legacy.
