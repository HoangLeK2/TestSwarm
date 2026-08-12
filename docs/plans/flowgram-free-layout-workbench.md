# FlowGram Free Layout Workbench Plan

Status: active
Last updated: 2026-08-07

## Goal

Deliver a production workflow workbench where users can discover and configure
nodes, build a graph, validate and save it, start a real device execution, and
observe that execution on the canvas.

The canvas must not imply semantics that the runtime does not support. A free
edge is only production-ready when validation and execution interpret it the
same way.

## Current Baseline

- The reusable FlowGram canvas uses `@flowgram.ai/fixed-layout-editor` and
  represents nested `steps[]`; it is not a free-position graph.
- Campaign and device-control screens already integrate the canvas with the
  comprehensive `StepDetailPanel`.
- The FlowGram add menu exposes only a small hard-coded subset of step types.
- Org scenarios already have body, validation, and preview APIs.
- Org scenario preview creates a tracked execution and starts Temporal when it
  is available.
- Backend graph validation reads edges, but `compile_graph_to_steps()` still
  derives execution order from fractional `order`. Arbitrary edges therefore
  cannot yet be presented as executable connections.

## Product Contract

The production editor uses an org scenario as its canonical entity. Templates
remain reusable starting points, not executable editor documents.

The long-term graph contract contains versioned nodes, edges, positions,
ports, variables, and viewport state. FlowGram's internal document is a UI
projection of that contract, not the persisted domain model.

Run and test are separate actions:

- **Run workflow** saves and validates the current org scenario, creates a real
  preview execution, and dispatches through the existing Temporal pipeline.
- **Test node/draft** may use direct device preview streaming and must be
  labelled as non-durable testing.

## Phase 1: Usable Org Scenario Editor

Scope:

- Enable the existing org scenario FlowGram route.
- Load and save through the org scenario body API.
- Preserve variables and existing graph metadata when editing sequence steps.
- Reuse `StepDetailPanel` as the selected-node inspector.
- Show dirty, saving, validating, valid, and invalid states.
- Validate the current draft through the org scenario validation API.
- Keep the fixed-layout semantics explicit in the UI.

Acceptance:

- Opening `/scenario-flow/org/{scenarioId}` no longer redirects.
- Existing steps load into the canvas.
- Selecting a node opens its complete inspector.
- Inspector changes update the canvas and become dirty changes.
- Save persists the current steps without dropping variables.
- Validate uses the unsaved draft and reports errors and warnings.
- Leaving with unsaved changes triggers the browser unload warning.

## Phase 2: Real Workflow Run

Scope:

- Add a run configuration dialog for device, account, input variables, and
  side-effect confirmation.
- Save and validate before starting.
- Call `POST /scenarios/{scenarioId}/preview`.
- Show execution ID, workflow ID, dispatch source, and start warnings.
- Subscribe or poll execution progress and map stable step IDs to canvas nodes.
- Support cancellation and navigation to execution details.
- Keep per-node streaming under a separate Test action.

Acceptance:

- Run is disabled for invalid or unsaved workflows unless save succeeds.
- A successful Run creates a persisted execution.
- Temporal receives `ScenarioWorkflow` when available.
- Refreshing the editor can restore the active execution display.

## Phase 3: Node Catalog And Search

Scope:

- Replace the hard-coded FlowGram adder list with a searchable palette.
- Consolidate title, description, category, keywords, default config, ports,
  runtime capabilities, and disabled reasons in one frontend catalog.
- Reconcile the catalog with backend `SCENARIO_STEP_TYPES` and `STEP_SCHEMA`.
- Add recent and favorite nodes after baseline search is stable.

Acceptance:

- Search works by title, alias, keyword, and category.
- Every enabled catalog entry has a default config, inspector, and runtime
  implementation.
- Unsupported nodes are hidden or disabled with a clear reason.

## Phase 4: Free Layout Canvas

Scope:

- Adopt a free-layout renderer and persist node positions and viewport.
- Support palette drag/drop, pan, zoom, selection, copy/paste, undo/redo,
  minimap, fit view, and auto-layout.
- Define typed input/output ports and connection constraints.
- Add adapters between the canonical workflow graph and the canvas document.
- Migrate existing `steps[]` scenarios into versioned graph documents.

Acceptance:

- Position and viewport survive save/reload.
- Connections survive round trips without losing port identity.
- The UI cannot create a connection that the current runtime cannot compile.

## Phase 5: Edge-Driven Runtime

Scope:

- Define start/end, success/failure, true/false, loop body/exit, join, and
  error-edge semantics.
- Make graph compilation traverse edges instead of fractional order.
- Share graph analysis between validation, compilation, and progress mapping.
- Reject accidental cycles while allowing explicit loop constructs.
- Version semantics so legacy scenarios retain their existing behavior.

Acceptance:

- The route connected by the user is exactly the route executed by Temporal.
- Validator and compiler agree on reachability, dead ends, branches, and loops.
- Compiler tests cover sequence, condition, loop, random branch, failure path,
  and sub-scenario execution.

## Phase 6: Production Hardening

Scope:

- Optimistic concurrency and version conflict handling.
- Version history and rollback.
- Large-graph performance and accessibility.
- Localisation, permission checks, observability, and analytics.
- End-to-end coverage for edit, save, validate, run, progress, cancel, and
  recovery after refresh.

## Delivery Gates

Each phase must pass focused unit tests, frontend type checking, strict lint for
touched files, and regression tests for existing campaign/device FlowGram
consumers. Backend compiler/runtime phases additionally require Python unit and
integration tests around validation and Temporal dispatch.
