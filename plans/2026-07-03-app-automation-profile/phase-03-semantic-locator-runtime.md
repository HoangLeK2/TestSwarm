# Phase 03: Semantic Locator Runtime

## Overview

Implement locator resolution as a scoring pipeline over `u2` hierarchy and screenshot metadata.

## Runtime Order

1. Existing exact selector: resourceId/text/description/xpath.
2. Selector chain: parent/child/sibling/instance.
3. Semantic candidates: label-near-field, class + bounds, clickable sibling.
4. Region-aware bounds: top/bottom/form row/tool bar.
5. OCR/image extension point only; no heavy OCR dependency in this phase.
6. Coordinate fallback only if explicitly allowed.

## Expected Files

- Modify current selector utilities after GitNexus impact analysis.
- Add a small runtime module if existing utility file would become too large.
- Add focused tests near existing scenario utility tests.

## Algorithm Requirements

- Return `LocatorResolution` with:
  - selected node
  - score
  - reason
  - candidate count
  - hierarchy source
  - fallback level
  - bounds
- Do not silently tap if score below threshold.
- If multiple high-score matches exist, fail with ambiguity unless profile allows `instance`.

## Tests

- Exact selector wins over heuristic.
- Label-near-input works when resourceId is missing.
- Duplicate text produces ambiguity unless index/instance supplied.
- Stale hierarchy refresh path is exercised.
- Popup masking path does not select hidden/covered node.
- Wrong-node regression: correct text exists but duplicated node should not be tapped by accident.

## Performance Gate

- Benchmark candidate scoring on small/medium/large hierarchy XML.
- Budget target: normal selector path stays close to current latency; heuristic path has explicit timing in step output.

## Review Gate

- `performance-reviewer`: scoring complexity and cache strategy.
- `reviewer`: correctness and failure semantics.

## Success Criteria

- Weak-resourceId screens can be handled with explainable selection.
- Failures produce enough detail to tune profile without guessing.

## Implementation Progress

- Added isolated XML-based resolver in `device_farm/services/app_automation_locator.py`.
- Added `HierarchySnapshot` so multiple locator/watch evaluations can share one parsed hierarchy.
- Added tests for exact selector, resource-id contains, label-near-field, explicit coordinate fallback, ambiguity, suffix labels, and region-scoped matching.
- Runtime integration exists for `login_if_needed`, `fill_form`, and `assert_app_state`.
- Generic replacement of existing `tap_selector` / `_execute_tap()` behavior remains out of scope for this first slice.
