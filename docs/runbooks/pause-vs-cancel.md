# Pause vs Cancel — execution control runbook

## When to use pause

Use **pause** when you need to stop **upcoming** steps but keep the run resumable:

- Device farm network blip — wait and resume without re-dispatching.
- Account rate limit — pause, rotate credentials or wait for cooldown, then resume.
- Operator needs to inspect device state mid-campaign.

Pause is **cooperative**: the current atomic step (single activity / batch) completes, then the workflow blocks before the next step. Checkpoint progress (steps 1–N) is preserved; resume continues from the next step without re-running completed steps.

## When to use cancel

Use **cancel** when the run must **terminate** and release resources:

- Wrong scenario or campaign configuration.
- Emergency stop — incident response.
- Run is no longer needed.

Cancel sends a stop signal to Temporal, marks the execution `cancelled`, and releases devices (account usage end + session lock release).

## Cancel does not undo

**Cancel is not undo.** Side effects already committed on external platforms remain:

- Social posts, comments, likes, messages sent before cancel stay live.
- Content already saved to the content store remains.
- Device screenshots and artifacts already captured are kept.

The API returns an explicit warning: *"Cancel does not undo posted side effects…"*

Operators must use platform-native tools to reverse mistaken actions if reversal is possible.

## API summary

| Action | Execution | Campaign |
|--------|-------------|----------|
| Pause | `POST /api/executions/{id}/pause` | `POST /api/campaigns/{id}/pause` |
| Resume | `POST /api/executions/{id}/resume` | `POST /api/campaigns/{id}/resume` |
| Cancel | `POST /api/executions/{id}/cancel` `{ "reason": "…" }` | `POST /api/campaigns/{id}/cancel` |

Campaign-level actions fan out to all `running` / `paused` executions and matching Temporal workflows.

## Error codes

| Code | HTTP | Meaning |
|------|------|---------|
| `INVALID_ACTION` | 409 | e.g. pause on `completed` / `cancelled` execution |
| `EXECUTION_NOT_FOUND` | 404 | Unknown execution id |

Pause and resume are **idempotent**: repeating pause on an already-paused execution returns `200` with `effective_transition: false`.

## Observability

- Audit: `activity_log` entries `execution.paused`, `execution.resumed`, `execution.cancelled`.
- Webhooks: same event names when org subscribes.
- DB: `pause_signal_received_at`, `cancel_signal_received_at`, `cancelled_at`, `cancel_reason` on `executions`.
