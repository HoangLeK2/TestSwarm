# Operator playbook — DLQ (Dead Letter Queue)

**Ticket:** DF-T-04-012 · **Persona:** Social Data Operator

## When an execution lands in DLQ

After automatic step retries (DF-T-04-011) are exhausted, the execution moves to
`dlq_open` and a row is created in `execution_dlq` with:

- `failed_step_id`, `failure_reason`, `failed_at`
- `artifact_refs` (screenshot URL when capture is enabled — DF-T-04-014)
- link to `execution_id`, `device_serial`, `campaign_id`

Domain event: `execution.dlq.opened`.

## Where to act

- **API:** `/api/executions/dlq*` (list, detail, retry, close, bulk-retry)
- **UI:** Campaign monitor → **Errors to fix** panel

## Decision guide: retry vs close

| Situation | Action | Notes |
|-----------|--------|-------|
| Device was offline / transient network | **Retry from checkpoint** | Default when fail was recent (< 1 h) |
| UI layout changed since fail | **Full re-run** | Safer when checkpoint state may be stale |
| Fail > 1 h ago | Prefer **full re-run** | Checkpoint resume may hit wrong screen |
| Scenario/config bug | **Close** with reason | e.g. `"scenario logic bug"` — marks `dlq_closed`, re-evaluates campaign |
| Not worth fixing (one-off test) | **Close** or **Dismiss** | Close is audited; dismiss is legacy soft-remove |
| Many devices failed same way | **Bulk retry** | Max 50 per request; review one entry first |

## Retry behavior

- Creates a **new execution** with `meta.replayed_from=<old_id>`.
- **Checkpoint** (`from_checkpoint: true`): resumes at last successful step (`start_step`).
- **Full** (`from_checkpoint: false`): runs from step 1; old artifacts are not overwritten.
- DLQ entry → `replayed` with `replayed_to_execution_id`.
- Concurrent retries: second request → `409 DLQ_RETRY_IN_PROGRESS`.

## Close behavior

- Execution → `dlq_closed`; DLQ row → `closed` with `closed_by`, `close_reason`.
- Campaign aggregator re-evaluates (open DLQ no longer blocks “all terminal”).
- Event: `execution.dlq.closed`.

## Campaign ↔ DLQ ↔ aggregator

- **Open DLQ** (`pending` / `retrying`) counts as non-terminal for campaign status.
- When all executions are terminal **or** DLQ-closed, campaign may move to `completed` / `failed`.
- If every execution is DLQ-open, campaign tends toward `failed`.

## KPI

- Target: DLQ entry processed (retry or close) within **24 h** for ≥ 90% of entries.
- Metric: `dlq_opened_total`, `dlq_replayed_total`, `dlq_closed_total`.

## Retention

DLQ rows are **not auto-purged** (audit). Retention policy: DF-E-09.
