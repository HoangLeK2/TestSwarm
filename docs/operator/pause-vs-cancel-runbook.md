# Pause vs Cancel — operator runbook (DF-T-04-016)

Use this guide when an execution or campaign needs to stop or wait during a run.

## When to pause

Pause when you expect to **continue later** from the same checkpoint:

- Device farm network blip — wait for devices to come back online.
- Account rate-limited temporarily — swap credentials or wait for cooldown.
- Need to inspect DLQ or logs before deciding next action (note: pause is **blocked** while an open DLQ entry exists — resolve or cancel instead).

**Behavior:**

1. `POST /api/executions/{id}/pause` (or campaign-level pause).
2. The **current step finishes** (atomic step semantics); the workflow stops before the next step.
3. Status becomes `paused`. Event `execution.paused` is emitted; audit log records before/after status.
4. Devices remain claimed until you resume or cancel.

**Resume:** `POST /api/executions/{id}/resume` — workflow continues from the next step; completed steps and artifacts are **not** re-run or overwritten.

## When to cancel

Cancel when the run should **stop permanently**:

- Wrong scenario or campaign configuration.
- Emergency stop — side effects already posted are acceptable to leave in place.
- Operator explicitly abandons the run.

**Behavior:**

1. `POST /api/executions/{id}/cancel` with optional `{ "reason": "..." }`.
2. Cancel signal is sent to Temporal; in-flight step may abort best-effort.
3. Status becomes `cancelled`; devices are **released** via account/session cleanup.
4. Remaining steps do **not** run.

## Cancel does not undo

> **Warning:** Cancel stops future work. It does **not** reverse actions already committed on external platforms (comments, likes, messages, posts, etc.).

The API response includes:

```text
Cancel does not undo posted side effects on external platforms (e.g. comments, likes, messages already sent).
```

If you need to reverse platform effects, use platform-specific tools or manual remediation — not execution cancel.

## Campaign-level control

| Action | Endpoint | Effect |
|--------|----------|--------|
| Pause all | `POST /api/campaigns/{id}/pause` | Fan-out pause to running executions; `campaign.status = paused` |
| Resume all | `POST /api/campaigns/{id}/resume` | Fan-out resume; `campaign.status = running` |
| Cancel all | `POST /api/campaigns/{id}/cancel` | Fan-out cancel; terminal campaign + executions |

Temporal signals are batched once per campaign to avoid duplicate signalling.

## Idempotency

- Pause on already-paused execution → `200`, `effective_transition: false`.
- Resume on already-running execution → `200`, `effective_transition: false`.
- Cancel on already-cancelled execution → `200`, `effective_transition: false`, warning still returned.

Concurrent duplicate requests are safe; only one effective state transition is recorded in audit.

## Errors

| Code | When |
|------|------|
| `404 EXECUTION_NOT_FOUND` | Unknown execution id |
| `409 INVALID_ACTION` | Pause/resume/cancel on terminal status, or pause with open DLQ |

## Observability

- **SSE / events:** `execution.paused`, `execution.resumed`, `execution.cancelled` on `/api/executions/{id}/events/stream`.
- **Activity log:** query `activity_log` (campaign/execution actions via existing logging) — includes `before_state`, `after_state`, `reason` when recorded.
- **Metrics:** `execution_control_total`, `execution_control_duration_seconds` (labels: `action`, `effective`).
