# Scenario validation rules (DF-T-04-004)

`POST /api/campaigns/{campaign_id}/scenarios/{scenario_id}/validate` runs shape, semantic, and lint checks.

## Performance notes

- Step tree is indexed once per scenario (`StepIndex`) — semantic/lint checks share that pass.
- `run_scenario` resolution preloads all campaign scenarios + version rows in **two DB queries** (not N+1 per ref).
- Graph BFS uses `deque`; `${var}` scan skips screenshot/media fields.

## Levels

| Level | Blocks save |
|-------|-------------|
| `error` | Yes (unless `force=true` on PATCH) |
| `warning` | No |
| `info` | No |

## Error codes

| Code | Description |
|------|-------------|
| `SHAPE_VALIDATION_FAILED` | Pydantic step/variable shape invalid (DF-T-04-002) |
| `GRAPH_UNREACHABLE_NODE` | Graph node not reachable from start |
| `GRAPH_DEAD_END_NODE` | Non-terminal node with no outgoing edges |
| `UNDECLARED_VARIABLE` | `${var}` used but not declared in scenario/campaign/set_variable |
| `SCENARIO_REF_NOT_FOUND` | `run_scenario` target missing |
| `SCENARIO_VERSION_NOT_FOUND` | `scenario_version` pin does not exist |
| `SCENARIO_REF_ARCHIVED` | Target scenario marked archived in `variables._meta.archived` |
| `SCENARIO_DEPTH_EXCEEDED` | Nesting depth > 10 |
| `CIRCULAR_SCENARIO_REFERENCE` | Cycle in `run_scenario` graph |
| `INVALID_ON_ERROR_TARGET` | `on_error` points to unknown step id |
| `INVALID_RETRY_CONFIG` | `retry.attempts` not in 1–10 or backoff params invalid |

## Warning codes

| Code | Description |
|------|-------------|
| `NO_VERIFICATION_STEP` | Interaction steps without `verify_screen` |
| `IMPLICIT_ACCOUNT_FALLBACK` | Social steps without account group / `__ACCOUNT_ID__` |

Disable `NO_VERIFICATION_STEP` per scenario: `variables._validation.skip_no_verification = true`.

## Example fixes

**Unreachable node:** connect an edge from the start node or remove the orphan.

**Undeclared variable:** add to `variables` or precede with `set_variable`.

**Invalid on_error:** set `on_error` to `pause`/`continue`/`stop` or an existing step `id`.
