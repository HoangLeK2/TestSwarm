# Execution event catalogue (DF-T-04-013)

**Schema version:** `1` · **Broker topic:** `df.execution.events.v1`

Consumers MUST treat delivery as **at-least-once** and dedupe on `event_id`.

## Envelope (all events)

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | UUID | Unique id — use for idempotent processing |
| `event_type` | string | Dot-separated type (see below) |
| `schema_version` | string | Payload schema version (`1`) |
| `occurred_at` | ISO8601 | Event timestamp (monotonic per execution) |
| `organization_id` | string | Tenant scope |
| `campaign_id` | string? | Campaign when applicable |
| `execution_id` | string | Execution row id |
| `step_id` | string? | Step identifier when step-level |
| `payload` | object | Type-specific fields |
| `tags` | string[] | Prefix tags for filter (e.g. `execution.dlq`) |

## Execution lifecycle

| event_type | When | payload (examples) |
|------------|------|---------------------|
| `execution.created` | Execution row created | `run_type`, `status` |
| `execution.started` | Status → running / device claimed | `dispatch_id`, `status` |
| `execution.completed` | All steps success, terminal completed | `device_serial`, `status` |
| `execution.failed` | Terminal failed (non-DLQ) | `status`, `message` |
| `execution.paused` | Operator pause (after current step completes) | `status`, `workflows_signalled` |
| `execution.resumed` | Operator resume from checkpoint | `status`, `workflows_signalled` |
| `execution.cancelled` | Operator cancel | `reason`, `status`, `devices_released` |
| `execution.dlq.opened` | Retries exhausted → DLQ | `dlq_id`, `failure_reason`, `artifact_refs` |
| `execution.dlq.replayed` | Operator replay | `replayed_to_execution_id`, `from_checkpoint` |
| `execution.dlq.closed` | Operator close | `close_reason`, `dlq_id` |

## Step lifecycle

| event_type | When | payload (examples) |
|------------|------|---------------------|
| `step.started` | Before step dispatch | `step_index`, `step_type` |
| `step.retried` | Retry policy backoff between attempts | `attempt`, `reason`, `wait_ms_before_next` |
| `step.completed` | Step ok | `step_index`, `ok: true` |
| `step.failed` | Step terminal fail | `reason_code`, `message` |

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/executions/{id}/events?since={event_id}` | Catch-up after disconnect |
| GET | `/api/executions/{id}/events/stream` | SSE live (`Last-Event-ID` resume) |

## Storage

- **Outbox:** `execution_events` rows with `published_at IS NULL`
- **Archive:** same table, `published_at` set; retained 30 days
- **Poller:** background loop every 1s publishes pending rows to in-process bus (Kafka/NATS hook ready)

## Consumer guide

1. Subscribe SSE or poll catch-up with last seen `event_id`.
2. On each message, `INSERT ... ON CONFLICT (event_id) DO NOTHING` in your projection.
3. Filter by `tags` prefix e.g. `execution.dlq` for notification rules (DF-E-09).
