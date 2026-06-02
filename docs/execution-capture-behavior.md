# Execution step capture (DF-T-04-014)

Epic 04 executions capture device evidence **by default** for every step. Capture is not opt-in per run unless explicitly disabled at step or org level.

## Default behavior

| Setting | Default | Override |
|---------|---------|----------|
| Pre-capture | ON | `pre_capture: false` on step |
| Post-capture | ON | `post_capture: false` on step |
| Fail snapshot | ON (sync) | Always taken when a step fails terminally |
| Legacy `capture_steps` flag | OFF unless set | Epic 04 runs with `execution_id` enable capture automatically |

Each capture produces:

- PNG screenshot (compressed to ≤ 200KB when possible)
- UI hierarchy XML (when device transport responds)
- Metadata stored on the step result as `artifacts[]` and legacy `screenshot_pre` / `screenshot` keys

## Fail-soft vs require_capture

- **Default (fail-soft):** capture errors log a warning and increment `capture_failure_total`; the step continues.
- **`require_capture: true`:** if pre/post/fail capture cannot be stored, the step fails with `reason_code=capture_required_failed`.

## Org throttle

Reduce storage cost by capturing only every Nth step:

```json
{
  "capture_throttle": 3
}
```

Set on scenario body, `scenario_config`, or campaign variable `__CAPTURE_THROTTLE__`. With `capture_throttle=3`, steps at index 0, 3, 6, … get pre/post capture; others are skipped and counted in `capture_skipped_throttle_total`.

## Async post-capture

Post-step capture runs asynchronously for successful steps so dispatch is not blocked. Fail snapshots and steps with `require_capture` run synchronously. The scenario executor flushes pending captures before returning final results.

## DLQ integration

Failed steps attach `type=fail` artifacts. DLQ `artifact_refs` include `screenshot_fail`, `screenshot_post`, and `hierarchy_url` for operator replay/debug (DF-T-04-012).

## Metrics

- `capture_success_total{phase=pre|post|fail}`
- `capture_failure_total{phase=...}`
- `capture_skipped_throttle_total`

## API

Step artifacts appear in:

- `GET /api/executions/{id}/artifacts` (from `passed_steps` / `failed_steps` JSON)
- DLQ entry `artifact_refs` on failure

Structured refs use `artifacts_json` on each step result (same array as `artifacts`).
