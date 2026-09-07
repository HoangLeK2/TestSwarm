# Phase 05 - Template Migration Strategy

## Goal

Separate reusable behavior templates from Facebook-specific templates.

## Files To Modify

- `/Users/hoangle/farm/device-farm/device_farm/db/seeds/scenario_templates.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/scenario_migrations/social_node_rename.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/scenario_validation/step_index.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/org_scenario_validation/step_index.py`
- `/Users/hoangle/farm/device-farm/front-end/src/features/scenario-templates/components/scenario-flow-editor/scenario-automation-map.tsx`

## Template Classes

- `generic`: device/input/control/extract examples.
- `social-neutral`: capability templates with `platform: auto` and platform variable.
- `facebook`: legacy or adapter-specific templates with explicit `platform: facebook`.

## Migration Rules

- Do not mutate existing saved scenario silently.
- New template copies must include platform contract metadata.
- Facebook templates remain available but category is `Facebook adapter`, not default catalog.
- Old platform-named nodes migrate to neutral type plus `platform: facebook`.
- Missing platform in old social nodes gets a validation warning first, then migration prompt.

## Acceptance

- Template list can filter generic/social/platform-specific.
- Facebook templates are clearly adapter-specific.
- Social-neutral templates do not contain Facebook package names, labels, or selector choreography.

