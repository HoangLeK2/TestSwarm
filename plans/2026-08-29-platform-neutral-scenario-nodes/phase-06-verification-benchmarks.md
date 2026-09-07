# Phase 06 - Verification And Benchmarks

## Goal

Verify correctness, compatibility, and speed after implementation.

## Test Timing Rule

Per user instruction: write tests after implementation changes, not before.

## Focused Tests To Add After Implementation

- Backend contract:
  - capability matrix includes Facebook active and draft platforms disabled.
  - unsupported platform does not execute Facebook code.
  - safe generic recipe can run without platform-specific adapter code.
  - adapter-required capability fails clearly when adapter is missing.
  - old Facebook scenarios still validate.
- Frontend:
  - node catalog labels are neutral.
  - platform select disables unsupported options with reason.
  - existing `platform: facebook` value is preserved.
  - trace chips show requested/resolved/execution mode/facets.
- Migration:
  - platform-named old nodes convert to neutral + `platform: facebook`.
  - missing platform warns/fails according to scenario age and migration mode.

## Commands

Backend focused:

```bash
cd device_farm
uv run pytest tests/test_epic08_social_ext.py tests/test_social_node_rename.py
uv run pytest tasks/scenario/tests/test_control_flow.py -k "social or platform"
```

Frontend focused:

```bash
cd front-end
pnpm exec node --loader ./scripts/ts-extension-loader.mjs --experimental-strip-types --test \
  src/features/campaigns/components/scenario-steps/types.test.ts \
  src/features/campaigns/lib/workflow-step-list-model.test.ts
pnpm exec eslint \
  src/features/campaigns/components/scenario-steps/types.ts \
  src/features/campaigns/components/flow-editor/platform-select.tsx \
  src/features/campaigns/hooks/use-platform-capabilities.ts
```

Repo hygiene:

```bash
git diff --check
```

## Benchmarks

Measure before/after:

- `usePlatformCapabilities` one-request capability matrix transform.
- Node catalog filter/render model for 1k nodes/options.
- Runtime resolver over 10k synthetic social steps.
- Execution event folding with requested/resolved platform trace fields.

Targets:

- capability matrix transform p95 under 5 ms for 20 platforms x 100 capabilities.
- catalog filtering p95 under 10 ms.
- resolver p95 under 1 ms per step with in-memory registry.
- no frontend per-node network requests.

## Acceptance

- Focused backend tests pass.
- Focused frontend tests pass.
- `git diff --check` clean or unrelated baseline issue documented.
- Benchmark shows no regression from platform resolution/capability UI.
