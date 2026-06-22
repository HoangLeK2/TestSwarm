# Spec: Improve Screen Element Finding Accuracy

## Assumptions

1. "Tim phan tu tren man hinh" means the selector-pick and selector-execution path used by device mirror, campaign step authoring, MCP `df_ui_elements` / `df_tap_selector`, and scenario `tap_selector` / `input_selector` / `wait_element`.
2. The main current failure is not only slow lookup; it is low precision: picking a visible UI item often produces a selector that later resolves to the wrong element, the first duplicate element, or a stale/different row after scroll.
3. We should not change the uiautomator APK or add a paid/external vision dependency for the first fix. The first fix should use hierarchy XML, bounds, package, selector uniqueness, fallback ratios, and existing image/healing phases.
4. The spec targets a bug-fix plan only. Implementation starts after this spec is reviewed.

## Objective

Make element finding accurate enough that a user can pick an element from the current device screen and have the saved step reliably target that same semantic element during execution.

The bug today is spread across multiple surfaces:

- `device_farm/api/routes/device_control/device_ui.py` exposes `/devices/{serial}/ui_elements`, but `_best_selector()` chooses `text`, then `resource-id`, then `description` without duplicate counts, package filtering, system UI filtering, or bounds-aware fallback.
- `front-end/src/features/devices/utils/hierarchy-hit-test.ts` and `hierarchy-xml-pick.ts` already contain stronger heuristics for mirror/XML picking, but those heuristics are not the canonical policy for all backend, MCP, and runtime callers.
- `device_farm/runtime/element_resolver.py` and `device_farm/tasks/scenario/utils.py` execute a phased pipeline, but the saved selector quality and runtime diagnostics are not strong enough to explain or recover from duplicate/stale selectors.
- `device_farm/runtime/core/device_client.py::tap_selector()` still has a direct manual-control path that can click the first matching selector when the selector is ambiguous.

Users affected:

- Operators building campaign scenarios from the live device mirror.
- MCP/agent workflows that call `df_ui_elements`, choose an element, then call `df_tap_selector`.
- Scenario execution paths that replay `tap_selector`, `input_selector`, `wait_element`, `if_element`, and `long_tap_selector`.

## Issue Definition

### Failure Modes

1. Duplicate selector wins incorrectly

   Android apps, launchers, and Facebook-like feeds often reuse the same `resource-id`, `text`, or generic content container across many rows. A selector such as `resource-id=com.example:id/item` resolves to the first match, not the row the user selected.

2. Selector generation differs by surface

   Frontend mirror picking uses ranked XML hit testing, while `/ui_elements` uses `_best_selector()`. MCP and older dashboard callers can therefore get lower-quality selectors than the mirror.

3. Coordinate and hierarchy dimensions can drift

   Status bar, nav bar, and SystemUI nodes appear in hierarchy XML and can distort coordinate mapping if screen dimensions are inferred from the wrong node. Existing frontend utility tests cover this, but backend/runtime parity is not guaranteed.

4. Volatile bounds XPath is used without explicit semantics

   `//*[@bounds="..."]` can be the best last-resort selector for the current screen, but it is volatile after scroll/layout changes. It must be saved with fallback ratio, screen dims, and diagnostics so execution can recover or explain failure.

5. Runtime result lacks enough evidence

   When element finding fails or clicks the wrong target, logs usually show selector not found/found, but not candidate rank, duplicate counts, chosen policy, bounds, package, or fallback phase.

## Tech Stack

- Backend/runtime: Python, FastAPI, existing `DeviceClient`, uiautomator2 JSON-RPC wrapper, `agent-boot` batch executor.
- Frontend: Next.js/React TypeScript utilities under `front-end/src/features/devices/utils`.
- XML parsing: existing Python XML helpers and browser `DOMParser`.
- Tests: `pytest` for Python, Node test runner for frontend utility modules.

## Commands

Exploration:

```bash
npx gitnexus query "find element on screen selector uiautomator xpath bounds tap action"
```

Frontend selector utility tests:

```bash
cd front-end && node --experimental-strip-types --test src/features/devices/utils/hierarchy-hit-test.test.ts
```

Python selector/runtime tests:

```bash
PYTHONPATH=device_farm uv run pytest device_farm/tests/test_u2_jsonrpc.py device_farm/tests/test_scenario_selector.py device_farm/tasks/scenario/tests/test_utils.py -q
```

Focused backend UI route tests to add:

```bash
PYTHONPATH=device_farm uv run pytest device_farm/tests/test_device_ui_elements.py -q
```

Diff safety:

```bash
git diff --check
npx gitnexus detect-changes
```

## Project Structure

Relevant source paths:

```text
device_farm/api/routes/device_control/device_ui.py
  Backend hierarchy, flat UI element list, tap-selector API.

device_farm/runtime/element_resolver.py
  Phased selector/image/fallback/healing resolution for tap steps.

device_farm/tasks/scenario/utils.py
  Current scenario tap execution pipeline using ElementResolver.

device_farm/runtime/core/device_client.py
  Manual/control tap_selector route and batch fallback behavior.

device_farm/runtime/transports/u2_jsonrpc.py
  Low-level find_element, find_element_with_bounds, xpath lookup.

device_farm/services/scenario_selector.py
  Normalized selector schema, conditions, chain, fallback conversion.

front-end/src/features/devices/utils/hierarchy-hit-test.ts
front-end/src/features/devices/utils/hierarchy-xml-pick.ts
front-end/src/features/devices/utils/hierarchy-selectors.ts
  Frontend selector scoring, XML hit testing, stable selector generation.
```

Tests should live beside the affected layer:

```text
front-end/src/features/devices/utils/hierarchy-hit-test.test.ts
front-end/src/features/devices/utils/hierarchy-xml-pick.test.ts
device_farm/tests/test_device_ui_elements.py
device_farm/tests/test_scenario_selector.py
device_farm/tasks/scenario/tests/test_utils.py
device_farm/tests/test_u2_jsonrpc.py
```

## Code Style

Selector decisions should be explicit, scored, and testable. Avoid hidden "first non-empty field wins" logic.

Example shape:

```python
@dataclass(frozen=True)
class SelectorCandidate:
    by: str
    value: str
    score: int
    reason: str
    bounds: dict[str, int] | None = None
    duplicate_count: int = 1
    volatile: bool = False


def choose_selector(node: Element, counts: SelectorCounts) -> SelectorCandidate | None:
    if node.resource_id and counts.resource_id[node.resource_id] == 1:
        return SelectorCandidate("resource-id", node.resource_id, 80, "unique resource-id")
    if node.content_desc and counts.description[node.content_desc] == 1:
        return SelectorCandidate("description", node.content_desc, 70, "unique content-desc")
    if node.text and counts.text[node.text] == 1:
        return SelectorCandidate("text", node.text, 60, "unique text")
    if node.bounds:
        return SelectorCandidate("xpath", build_bounds_xpath(node.bounds), 20, "bounds fallback", volatile=True)
    return None
```

Conventions:

- Prefer unique semantic selectors over coordinates.
- Treat duplicate `resource-id` as unsafe unless disambiguated by conditions, chain, package, instance, or verified bounds.
- Treat generic layout/container classes as weak or invalid direct targets.
- Preserve fallback ratio and screen dimensions with volatile selectors.
- Log selector policy, candidate rank, duplicate count, package, and bounds for failed/ambiguous resolutions.

## Testing Strategy

### Fixture Corpus

Create XML fixtures for these cases:

- Launcher grid where every icon shares one `resource-id` and only text/desc is unique.
- Facebook-like feed row where the target semantic text/description is a child or sibling of a clickable container.
- Duplicate text buttons such as multiple "Like" / "Join" / "Comment" nodes.
- SystemUI/status/nav-bar nodes before the app root.
- Bounds-only fallback where no unique semantic selector exists.
- Stale `current_app` package where strict package filter returns zero candidates and must fall back to foreground non-system nodes.

### Unit Tests

- Frontend: candidate ranking and mirror hit-test behavior in `hierarchy-hit-test.test.ts` and a new `hierarchy-xml-pick.test.ts`.
- Backend: `/ui_elements` selector generation should match the same policy as frontend for duplicate IDs, unique desc/text, system UI filtering, and bounds fallback.
- Runtime: `_retry_find_element()` and `ElementResolver` should prefer bounded/verified selector results, surface fallback method, and not silently click ambiguous selector matches.
- JSON-RPC: xpath and bounds lookup should return stable parsed bounds and never normalize unsupported selector names incorrectly.

### Integration / Manual Verification

- Pick an element from mirror, save it into `tap_selector`, execute once on the same screen, and verify the tapped bounds match the picked candidate.
- Use `df_ui_elements` followed by `df_tap_selector` on a duplicate-heavy screen and verify the chosen element is not the first duplicate unless it is the intended one.
- Run a small scenario with `tap_selector` plus fallback ratio after a scroll and verify logs explain whether selector, healing, image, or fallback was used.

## Boundaries

- Always:
  - Run GitNexus impact analysis before editing any function/class/method symbol.
  - Keep selector policy changes covered by fixture-based tests.
  - Preserve legacy flat `by`/`value` scenario compatibility.
  - Include diagnostics for ambiguous or volatile picks.
  - Run `git diff --check` and `npx gitnexus detect-changes` before closing an implementation PR.

- Ask first:
  - Changing uiautomator APK/server behavior.
  - Adding OCR/vision/model dependencies.
  - Changing scenario JSON schema in a backward-incompatible way.
  - Removing the legacy dashboard `/ui_elements` response fields.

- Never:
  - Use duplicate `resource-id` as a stable primary selector without disambiguation.
  - Silently convert a failed selector into a raw coordinate tap without recording the fallback method.
  - Treat `class name` layout containers as reliable tap targets.
  - Hide duplicate candidates from diagnostics when accuracy is the failure being debugged.

## Implementation Plan

### Phase 1: Baseline and Golden Fixtures

Add XML fixtures and tests that reproduce the current bad behavior. The goal is to prove the bug before changing policy.

Deliverables:

- Fixture XMLs or inline test fixtures for duplicate ID, duplicate text, SystemUI dimensions, list-row semantic child/sibling, and bounds-only fallback.
- Tests showing current `/ui_elements` and runtime/manual selector behavior chooses unsafe selectors.

### Phase 2: Canonical Selector Policy

Create one selector policy contract and apply it to backend `/ui_elements`, frontend picker parity, and scenario saved selector shape.

Design:

- Count duplicate `resource-id`, `text`, and `content-desc` before choosing.
- Filter SystemUI and infer foreground app package when no explicit package is supplied.
- Rank candidates by semantic strength, uniqueness, depth, clickability, area, and container penalty.
- Emit multiple candidates for a point or element, not only one hidden choice.
- Mark bounds XPath as `volatile` and attach fallback ratio/screen dims.

### Phase 3: Runtime Verification and Fallback Behavior

Harden execution so a saved selector is verified against bounds/fallback hints when possible.

Design:

- If selector resolves with bounds and recorded fallback point is inside/tolerably near those bounds, tap recorded point or center according to the current resolver rule.
- If selector resolves outside expected bounds and there are alternative candidates, try healing before raw coordinate fallback.
- If only bounds XPath exists, use it as a current-screen selector but log volatility and require fallback metadata for replay.
- Ensure manual `DeviceClient.tap_selector()` and scenario execution do not diverge in selector normalization.

### Phase 4: Observability

Add structured logs/results for candidate selection and execution:

- selected `by/value`
- duplicate counts
- package
- bounds
- score/reason
- volatile flag
- resolution phase used: `selector`, `healed_selector`, `image_match`, `fallback_position`

### Phase 5: UI/MCP Contract Polish

Expose enough candidate metadata for humans and agents:

- Show why a selector was picked.
- Show duplicate/volatile warnings.
- Let users choose an alternate candidate when multiple overlap the tap point.
- Keep MCP `df_ui_elements` simple but return safe selectors by default.

## Tasks

- [ ] Task: Add failing selector fixture tests
  - Acceptance: Tests reproduce duplicate ID/text and SystemUI coordinate issues without real devices.
  - Verify: `cd front-end && node --experimental-strip-types --test src/features/devices/utils/hierarchy-hit-test.test.ts src/features/devices/utils/hierarchy-xml-pick.test.ts`
  - Files: `front-end/src/features/devices/utils/*test.ts`, `device_farm/tests/test_device_ui_elements.py`

- [ ] Task: Implement backend selector candidate policy
  - Acceptance: `/devices/{serial}/ui_elements` no longer returns duplicate unsafe `resource-id` as the default selector when unique text/desc or bounds fallback exists.
  - Verify: `PYTHONPATH=device_farm uv run pytest device_farm/tests/test_device_ui_elements.py -q`
  - Files: `device_farm/api/routes/device_control/device_ui.py`, optional shared helper under `device_farm/runtime/`

- [ ] Task: Align frontend picker and backend policy
  - Acceptance: Frontend mirror pick and backend UI element list choose equivalent top candidates for the golden fixtures.
  - Verify: frontend Node utility tests plus backend fixture tests.
  - Files: `front-end/src/features/devices/utils/hierarchy-hit-test.ts`, `front-end/src/features/devices/utils/hierarchy-xml-pick.ts`, backend selector helper/tests

- [ ] Task: Harden runtime selector execution
  - Acceptance: Ambiguous selector matches are verified by bounds/fallback where available; fallback phase is visible in result/logs.
  - Verify: `PYTHONPATH=device_farm uv run pytest device_farm/tasks/scenario/tests/test_utils.py device_farm/tests/test_u2_jsonrpc.py -q`
  - Files: `device_farm/runtime/element_resolver.py`, `device_farm/tasks/scenario/utils.py`, `device_farm/runtime/core/device_client.py`

- [ ] Task: Add diagnostics to UI/MCP responses
  - Acceptance: Candidate metadata exposes duplicate count, package, score reason, bounds, and volatility without breaking existing `selector_by` / `selector_value` fields.
  - Verify: API route tests and manual `df_ui_elements` smoke check.
  - Files: `device_farm/api/routes/device_control/device_ui.py`, `device_farm/mcp/server.py`, generated API only if contract changes require it

## Success Criteria

- Duplicate `resource-id` is not selected as the primary selector when it can target the wrong node.
- Mirror pick, XML tree pick, backend `/ui_elements`, and MCP `df_ui_elements` follow the same selector ranking principles.
- Bounds-only XPath is treated as volatile and paired with fallback metadata, not presented as a normal stable selector.
- Scenario execution logs identify which resolution phase clicked the element.
- Golden fixture tests cover duplicate selectors, SystemUI dimensions, semantic child/sibling rows, and bounds fallback.
- Existing legacy scenario steps with flat `by`/`value` still run.

## Open Questions

1. Should the first implementation prioritize MCP/agent accuracy (`df_ui_elements` -> `df_tap_selector`) or human scenario editor accuracy from the mirror?
2. Should volatile bounds XPath be allowed by default, or only when the user explicitly accepts a warning?
3. Do we want selector candidate metadata added to the public OpenAPI contract now, or keep it internal/backward-compatible in the existing JSON response first?
4. What is the minimum acceptable manual success rate for the first release: for example, 8/10 correct picks on duplicate-heavy Facebook/launcher screens?
