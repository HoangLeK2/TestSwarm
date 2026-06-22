# Implementation Plan: Element Finding Accuracy Fix

## Overview

This plan breaks `docs/plans/element-finding-accuracy-fix.md` into small, ordered implementation tasks. The work fixes low-accuracy element selection across three related paths: backend `/devices/{serial}/ui_elements`, MCP `df_get_ui_elements` -> `df_tap_selector`, and scenario/runtime `tap_selector` replay. The first release should preserve all existing response fields and legacy flat `by` / `value` scenario steps.

No uiautomator APK changes, OCR/model dependencies, or backward-incompatible scenario schema changes are included in this plan.

## Dependency Graph

```text
Golden XML fixtures and failing tests
    |
    +-- Backend selector policy for /ui_elements
    |       |
    |       +-- MCP df_get_ui_elements metadata and descriptions
    |
    +-- Frontend picker parity tests
            |
            +-- Optional frontend metadata display

Backend selector policy and runtime selector metadata
    |
    +-- ElementResolver / scenario tap diagnostics
            |
            +-- Manual end-to-end verification
```

Implementation order follows this graph: lock failing behavior first, fix the backend/MCP path that agents use directly, then align frontend and runtime replay.

## Architecture Decisions

- Keep the first implementation backward-compatible: `selector_by`, `selector_value`, `text`, `resource_id`, `content_desc`, `bounds`, and `clickable` remain in `/ui_elements`.
- Treat selector quality as a policy with explicit reasons and metadata, not a hidden `_best_selector()` field order.
- Use fixture parity instead of trying to share TypeScript code with Python. Backend and frontend can have separate implementations, but golden XML fixtures/tests should prove they choose equivalent safe selectors.
- Treat `//*[@bounds="..."]` as a volatile current-screen fallback. It can be returned, but must carry diagnostic metadata so callers do not mistake it for a stable semantic selector.
- Run GitNexus impact analysis before any implementation task edits a function/class/method symbol.

## Task List

### Phase 1: Golden Fixtures and Baseline Failures

## Task 1: Add Backend Selector Accuracy Fixtures

**Description:** Add focused Python tests for `/devices/{serial}/ui_elements` selector choice using inline or file-based XML fixtures. These tests should capture the current bad behavior before policy changes: duplicate `resource-id`, duplicate text, SystemUI nodes, launcher grids, and bounds-only fallback.

**Acceptance criteria:**

- [ ] Tests include at least one duplicate `resource-id` fixture where unique text/description should win.
- [ ] Tests include SystemUI/status/nav nodes and assert they do not become preferred selectors.
- [ ] Tests assert the response keeps legacy `selector_by` / `selector_value` fields.

**Verification:**

- [ ] Run `PYTHONPATH=device_farm uv run pytest device_farm/tests/test_device_ui_elements.py -q`.
- [ ] Confirm the initial version fails for the currently unsafe selector behavior, then passes after Task 3.

**Dependencies:** None.

**Files likely touched:**

- `device_farm/tests/test_device_ui_elements.py`

**Estimated scope:** Small: 1 file.

## Task 2: Add Frontend Picker Parity Fixtures

**Description:** Add frontend utility tests for `listSelectorCandidatesInXml()` and `pickStableHierarchySelector()` using the same scenario shapes as the backend tests. This locks the intended frontend behavior and avoids regressing the existing mirror picker.

**Acceptance criteria:**

- [ ] Duplicate launcher/icon `resource-id` resolves to unique text or description.
- [ ] A Facebook-like row can choose a semantic child/sibling selector instead of the outer container.
- [ ] Bounds and screen-dimension behavior is covered for status/nav-bar hierarchy dumps.

**Verification:**

- [ ] Run `cd front-end && node --experimental-strip-types --test src/features/devices/utils/hierarchy-hit-test.test.ts src/features/devices/utils/hierarchy-xml-pick.test.ts`.

**Dependencies:** None.

**Files likely touched:**

- `front-end/src/features/devices/utils/hierarchy-hit-test.test.ts`
- `front-end/src/features/devices/utils/hierarchy-xml-pick.test.ts`

**Estimated scope:** Small: 1-2 files.

### Checkpoint: Baseline

- [ ] Backend and frontend selector fixture tests exist.
- [ ] The failing cases are specific enough to identify wrong selector choice, not just "not found".
- [ ] No production code is changed except test-only fixture helpers.

### Phase 2: Backend and MCP Selector Contract

## Task 3: Replace `_best_selector()` With Ranked Backend Selector Policy

**Description:** Replace the backend's simple `_best_selector(text, rid, desc)` policy with a ranked candidate policy inside `device_ui.py` or a small helper. The policy should count duplicate `resource-id`, `text`, and `content-desc`, penalize SystemUI/layout containers, prefer unique semantic selectors, and fall back to volatile bounds XPath only when needed.

**Acceptance criteria:**

- [ ] Duplicate `resource-id` is not returned as the primary selector when unique text or description exists.
- [ ] `description` / `text` / unique `resource-id` ranking is deterministic and covered by tests.
- [ ] Bounds XPath fallback is marked with metadata such as `selector_volatile: true` and a reason.
- [ ] Existing `/ui_elements` fields remain backward-compatible.

**Verification:**

- [ ] Before editing, run `npx gitnexus impact _best_selector` and `npx gitnexus impact build_device_ui_router`; report direct callers and risk.
- [ ] Run `PYTHONPATH=device_farm uv run pytest device_farm/tests/test_device_ui_elements.py -q`.
- [ ] Run `PYTHONPATH=device_farm uv run pytest device_farm/tests/test_u2_bug_fixes.py -q` if `_best_selector` compatibility is affected.

**Dependencies:** Task 1.

**Files likely touched:**

- `device_farm/api/routes/device_control/device_ui.py`
- `device_farm/tests/test_device_ui_elements.py`

**Estimated scope:** Medium: 2 files.

## Task 4: Surface Safe Selector Metadata Through MCP

**Description:** Update MCP tool descriptions and schema wording to reflect the safer selector contract. Keep `df_get_ui_elements` returning the backend response directly, but make the tool description tell agents to prefer `selector_by` / `selector_value`, respect duplicate/volatile warnings, and pass supported selector kinds to `df_tap_selector`.

**Acceptance criteria:**

- [ ] MCP docs mention duplicate/volatile metadata if present.
- [ ] `df_tap_selector` allows every selector type returned by `/ui_elements`, including `description` and `xpath` if backend emits them.
- [ ] No external action or credential behavior changes.

**Verification:**

- [ ] Before editing, run `npx gitnexus impact _df_get_ui_elements` and `npx gitnexus impact _df_tap_selector`; report direct callers and risk.
- [ ] Run `PYTHONPATH=device_farm uv run pytest device_farm/tests/test_epic10_mcp_contract.py -q`.
- [ ] Manually inspect `device_farm/mcp/server.py` tool descriptions for consistency.

**Dependencies:** Task 3.

**Files likely touched:**

- `device_farm/mcp/server.py`
- `device_farm/tests/test_epic10_mcp_contract.py` only if existing contract tests need an assertion update.

**Estimated scope:** Small: 1-2 files.

### Checkpoint: Agent-Facing Flow

- [ ] `df_get_ui_elements` returns safer default selectors for duplicate-heavy fixtures.
- [ ] `df_tap_selector` accepts the selector kinds that `df_get_ui_elements` can return.
- [ ] Backend and MCP focused tests pass.

### Phase 3: Frontend Picker Alignment

## Task 5: Align Frontend Candidate Metadata With Backend Policy

**Description:** Extend frontend selector candidates only where needed to carry policy metadata equivalent to backend: duplicate count, reason, volatile flag, and package. This is not a visual redesign; it makes the candidate model explicit so later UI surfaces can warn correctly.

**Acceptance criteria:**

- [ ] `listSelectorCandidatesInXml()` exposes enough metadata to explain why the top candidate was chosen.
- [ ] Existing `by`, `value`, `selector`, and `bounds` consumers continue to work.
- [ ] Tests prove frontend and backend choose the same top selector for the golden duplicate/resource fixtures.

**Verification:**

- [ ] Before editing, run `npx gitnexus impact listSelectorCandidatesInXml` and `npx gitnexus impact pickStableHierarchySelector`; report direct callers and risk.
- [ ] Run `cd front-end && node --experimental-strip-types --test src/features/devices/utils/hierarchy-hit-test.test.ts src/features/devices/utils/hierarchy-xml-pick.test.ts`.

**Dependencies:** Tasks 2 and 3.

**Files likely touched:**

- `front-end/src/features/devices/utils/hierarchy-hit-test.ts`
- `front-end/src/features/devices/utils/hierarchy-xml-pick.ts`
- `front-end/src/features/devices/utils/hierarchy-hit-test.test.ts`
- `front-end/src/features/devices/utils/hierarchy-xml-pick.test.ts`

**Estimated scope:** Medium: 4 files.

## Task 6: Show Selector Warnings in Existing Picker UI

**Description:** Add minimal UI treatment in the existing picker/control-record surface for volatile or ambiguous selectors. This should be constrained to existing surfaces, not a redesign.

**Acceptance criteria:**

- [ ] Users can see when a selector is bounds-based/volatile.
- [ ] Users can see when a selector was chosen because duplicate IDs were unsafe.
- [ ] Existing "add tap_selector" and "pick selector" flows still write the same scenario shape.

**Verification:**

- [ ] Before editing, run `npx gitnexus impact ControlRecordView` or the exact component symbol found by GitNexus; report direct callers and risk.
- [ ] Run the frontend selector utility tests from Task 5.
- [ ] Run the existing frontend lint/typecheck command used by the repo if available for touched files.

**Dependencies:** Task 5.

**Files likely touched:**

- `front-end/src/features/devices/components/control-record-view.tsx`
- `front-end/src/features/devices/utils/control-record-xml.ts`
- Relevant component test only if an existing harness supports it.

**Estimated scope:** Medium: 2-3 files.

### Checkpoint: Human Picker Flow

- [ ] Mirror/XML pick still returns correct top candidates.
- [ ] Selector warnings are visible where the user picks a selector.
- [ ] Frontend tests pass without relying on alias-heavy component trees unless an existing harness already supports them.

### Phase 4: Runtime Replay and Diagnostics

## Task 7: Harden Scenario `ElementResolver` Diagnostics

**Description:** Make runtime resolution outcomes explicit. Preserve the current selector -> healing -> image -> ratio order, but ensure messages/logs include selector method, bounds, fallback point, and whether the click used center, recorded point, healed selector, image match, or raw fallback.

**Acceptance criteria:**

- [ ] `ResolveResult.message` or surrounding logs identify the resolution phase and chosen tap coordinates.
- [ ] Bounds-mismatch behavior is covered by tests.
- [ ] Raw ratio fallback remains visible as `fallback_position`, not hidden as selector success.

**Verification:**

- [ ] Before editing, run `npx gitnexus impact phase_selector` and `npx gitnexus impact ElementResolver`; report direct callers and risk.
- [ ] Run `PYTHONPATH=device_farm uv run pytest device_farm/tasks/scenario/tests/test_utils.py -q`.
- [ ] Run `PYTHONPATH=device_farm uv run pytest device_farm/tests/test_fixes.py -q` if existing tap resolver regressions live there.

**Dependencies:** Task 3.

**Files likely touched:**

- `device_farm/runtime/element_resolver.py`
- `device_farm/tasks/scenario/utils.py`
- `device_farm/tasks/scenario/tests/test_utils.py`

**Estimated scope:** Medium: 3 files.

## Task 8: Align Manual `tap_selector()` With Safer Selector Semantics

**Description:** Harden `DeviceClient.tap_selector()` so manual/MCP control does not silently behave worse than scenario execution. It should normalize selector names consistently, accept selector kinds emitted by `/ui_elements`, and log enough evidence when batch and legacy paths diverge.

**Acceptance criteria:**

- [ ] `description`, `descriptionContains`, `descriptionStartsWith`, `text`, `resource-id`, `xpath`, and `class name` behavior is covered or explicitly documented.
- [ ] Batch path and legacy fallback log route, selector, found/miss, and elapsed time.
- [ ] Existing manual-control behavior remains backward-compatible.

**Verification:**

- [ ] Before editing, run `npx gitnexus impact tap_selector` and `npx gitnexus impact _tap_selector_legacy`; report direct callers and risk.
- [ ] Run `PYTHONPATH=device_farm uv run pytest device_farm/tests/test_u2_jsonrpc.py device_farm/tasks/scenario/tests/test_utils.py -q`.

**Dependencies:** Tasks 3 and 7.

**Files likely touched:**

- `device_farm/runtime/core/device_client.py`
- `device_farm/tests/test_u2_jsonrpc.py`
- `device_farm/tasks/scenario/tests/test_utils.py`

**Estimated scope:** Medium: 3 files.

### Checkpoint: Runtime Flow

- [ ] Scenario replay and manual/MCP tap paths use compatible selector semantics.
- [ ] Runtime logs expose the resolution phase used for a tap.
- [ ] Focused Python runtime tests pass.

### Phase 5: End-to-End Verification and Cleanup

## Task 9: Add Manual Smoke Script or Runbook

**Description:** Add a short runbook for validating element accuracy on a real device without creating new production code. It should cover launcher duplicate IDs, a Facebook-like feed/list, and MCP `df_get_ui_elements` -> `df_tap_selector`.

**Acceptance criteria:**

- [ ] Runbook lists exact endpoints/tools and expected observations.
- [ ] Runbook includes what logs to search for when a selector fails.
- [ ] Runbook does not require credentials or paid services.

**Verification:**

- [ ] Review the runbook against the implemented API/tool names.
- [ ] If a device is available, execute one live pass and paste command/log evidence into the implementation summary.

**Dependencies:** Tasks 3, 4, 7, 8.

**Files likely touched:**

- `docs/runbooks/element-finding-accuracy.md`

**Estimated scope:** Small: 1 file.

## Task 10: Final Regression Gate

**Description:** Run the focused regression set, map changed symbols with GitNexus, and summarize the blast radius before closing the fix.

**Acceptance criteria:**

- [ ] All focused backend/frontend/runtime tests from previous tasks pass.
- [ ] `git diff --check` passes.
- [ ] `npx gitnexus detect-changes` shows only expected symbols/flows.
- [ ] Implementation summary states which open questions were resolved or deferred.

**Verification:**

- [ ] Run `git diff --check`.
- [ ] Run `npx gitnexus detect-changes`.
- [ ] Run the focused test commands listed in Tasks 1-8.

**Dependencies:** Tasks 1-9.

**Files likely touched:**

- No production files expected unless cleanup is needed.

**Estimated scope:** Small: verification only.

## Parallelization Opportunities

- Tasks 1 and 2 can run in parallel because backend and frontend fixture tests are independent.
- Task 4 can start after Task 3 defines the response metadata, while Task 5 continues frontend parity work.
- Task 9 can be drafted after the API/tool names stabilize, before runtime hardening is fully complete.

Must stay sequential:

- Task 3 before Task 4, because MCP should document the actual backend response.
- Task 3 before Task 7, because runtime diagnostics should reflect the final selector metadata language.
- Task 7 before Task 8, because manual `tap_selector()` should align with the runtime resolver rather than define a separate policy first.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Backend and frontend policies drift | High | Use shared golden fixture scenarios and assert equivalent top selectors. |
| Bounds XPath improves same-screen picking but fails after scroll | Medium | Mark bounds selectors volatile and require fallback metadata/diagnostics. |
| MCP agents still choose unsafe raw fields | Medium | Keep `selector_by` / `selector_value` as the canonical output and update tool descriptions. |
| Runtime changes affect unrelated tap scenarios | High | Keep resolver phase order unchanged and add focused tests for fallback behavior. |
| GitNexus impact returns high risk for shared symbols | Medium | Stop before edits, report blast radius, and split the affected task further. |

## Open Questions

- Should Task 3 return all candidate alternatives in `/ui_elements`, or only the selected candidate plus metadata for the first release?
- Should volatile bounds XPath be allowed automatically, or hidden behind an explicit UI warning/action in Task 6?
- Should MCP `df_tap_selector` accept only selectors emitted by `df_get_ui_elements`, or continue accepting arbitrary user-provided selectors?
- What manual success threshold is acceptable for the first device pass: 8/10, 9/10, or a specific fixture/device matrix?

## Ready-To-Implement Checklist

- [ ] Human has approved this task order.
- [ ] Open questions above are resolved or explicitly deferred.
- [ ] First implementation task starts with GitNexus impact analysis for any symbol it edits.
- [ ] No task is larger than five likely touched files.
- [ ] Each task has acceptance criteria and verification commands.
