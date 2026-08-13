# Execution Log Standard Research

Date: 2026-08-13

## Executive Summary

The current repo already has the raw pieces needed for a good monitoring/log system: `execution_events`, `execution_steps`, `execution_artifacts`, `execution_dlq`, `activity_log`, Temporal workflow progress, and SSE. The problem is not missing storage. The problem is ownership and presentation: several sources are used side-by-side without one clear read model.

The recommended standard is:

- `execution_events` is the canonical append-only timeline.
- `execution_steps` is a projection/snapshot derived from events and final results.
- `execution_artifacts` stores evidence, not log text.
- `execution_dlq` stores failures requiring operator action.
- `activity_log` stores audit/user/system control actions, not step runtime.
- Temporal remains the runtime engine and optional visibility/search index, not the product log source of truth.

The unified UI should show one "Run Trace" surface per execution/campaign/device/account. It should answer immediately:

- Which phone ran this?
- Which account ran this?
- Which campaign/scenario/step is this?
- What action happened?
- What target was involved?
- What was the result?
- What screenshot/XML/artifact proves it?
- If failed, what should the operator do next?

## Research Methodology

Sources consulted:

- OpenTelemetry Logs Data Model.
- OpenTelemetry Semantic Conventions.
- OpenTelemetry Resource Semantic Conventions.
- Google Cloud structured logging docs.
- Elastic Common Schema.
- Temporal observability and visibility docs.
- Current `device-farm` code paths around execution events, steps, artifacts, DLQ, and monitor UI.

Key search terms:

- structured logging best practices
- OpenTelemetry logs data model trace_id span_id attributes
- semantic conventions logs resources
- Temporal workflow observability search attributes
- Elastic Common Schema trace fields

## External Findings

OpenTelemetry's log model is stable and separates top-level log fields from structured attributes. The core idea maps well to this repo: keep a common envelope, then put domain-specific keys under attributes/details.

Important OpenTelemetry fields:

- `Timestamp`
- `ObservedTimestamp`
- `TraceId`
- `SpanId`
- `SeverityText`
- `SeverityNumber`
- `Body`
- `Resource`
- `Attributes`
- `EventName`

OpenTelemetry Semantic Conventions exist so every service uses the same attribute names for the same concept. For this repo, that means no more mixed names like `organization_id` vs `org_id`, `device_serial` vs serial parsed from workflow id, or step status derived differently in each UI component.

Google Cloud structured logging confirms the operational value: JSON logs are queryable by field and can be indexed. Plain text is only searchable as text and does not support precise filtering.

Elastic Common Schema reinforces the same point with `trace.id`, `span.id`, and `transaction.id` for correlation across events. This repo can use OpenTelemetry names internally and optionally map to ECS for export.

Temporal observability is useful for runtime state, metrics, traces, and search attributes. But Temporal visibility should not be the durable business log. Product-level trace should be persisted in the app DB because it must join account, phone, target, screenshot/XML, campaign, and operator actions.

## Current Repo Diagnosis

Current durable tables and responsibilities:

- `execution_events`: append-only event store and outbox for SSE.
- `execution_steps`: per-step checkpoint/snapshot.
- `execution_artifacts`: screenshot/XML/object metadata.
- `execution_dlq`: failed execution queue and retry/close state.
- `activity_log`: audit/control/action trail.
- `content_items`: crawled content and extracted content data.

Current UI/runtime sources:

- Campaign monitor lists workflows from Temporal.
- Workflow progress polls Temporal parent/child workflow queries.
- Expanded card subscribes to SSE from `execution_events`.
- Step list can read Temporal step logs.
- Artifact panel reads execution results, persisted step rows, and content artifacts.
- DLQ panel reads `execution_dlq`.

This creates several consistency risks:

- The same step can be represented by Temporal child state, `execution_events`, `execution_steps`, and final result JSON.
- UI components reconcile data locally instead of receiving one normalized backend read model.
- Some context, such as account, phone, step path, target, and artifact refs, is not guaranteed on every event.
- Long-running runs need aggregate counters, but counters are currently inferred from step details or separate workflow progress.
- Debugging requires jumping across monitor card, artifacts, DLQ, execution result, and raw events.

## Recommended Domain Model

Use one canonical event envelope.

```json
{
  "event_id": "uuid",
  "schema_version": "1",
  "event_name": "execution.step.completed",
  "event_type": "step.completed",
  "severity": "INFO",
  "occurred_at": "2026-08-13T10:15:30.123Z",
  "observed_at": "2026-08-13T10:15:30.200Z",
  "trace_id": "run-or-dispatch-correlation-id",
  "span_id": "step-attempt-id",
  "parent_span_id": "execution-or-loop-span-id",
  "message": "liked matched post",
  "resource": {
    "service.name": "device-farm",
    "service.component": "scenario-runtime",
    "deployment.environment": "local"
  },
  "context": {
    "org_id": "uuid",
    "campaign_id": "uuid",
    "execution_id": "uuid",
    "workflow_id": "exec_uuid",
    "scenario_id": "uuid",
    "scenario_version_id": "uuid",
    "scenario_ref_id": "uuid",
    "device_id": "uuid",
    "device_serial": "RF8...",
    "account_id": "uuid",
    "account_platform": "facebook",
    "account_label": "masked display label"
  },
  "step": {
    "step_index": 12,
    "step_path": "steps.3.then.1",
    "step_depth": 1,
    "step_id": "like_matched_post",
    "step_type": "social_action",
    "attempt": 1,
    "loop_iteration": 4
  },
  "action": {
    "action_type": "like",
    "platform": "facebook",
    "status": "completed",
    "duration_ms": 842,
    "selector_strategy": "u2_xml",
    "matched_text": "Like",
    "bounds": [100, 1200, 240, 1260]
  },
  "target": {
    "target_type": "post",
    "target_id": "external-or-derived-id",
    "target_label": "visible title or hash",
    "keyword": "booking",
    "match_reason": "keyword"
  },
  "artifacts": {
    "screenshot_before_id": "uuid",
    "screenshot_after_id": "uuid",
    "hierarchy_before_id": "uuid",
    "hierarchy_after_id": "uuid"
  },
  "result": {
    "ok": true,
    "counters_delta": {
      "matched": 1,
      "liked": 1,
      "commented": 0,
      "skipped": 0
    }
  },
  "error": null
}
```

## Required Fields

Every runtime event must include these fields:

- `event_id`
- `schema_version`
- `event_name`
- `event_type`
- `severity`
- `occurred_at`
- `trace_id`
- `context.org_id`
- `context.execution_id`
- `context.device_id`
- `context.device_serial`
- `context.account_id` when the scenario requires an account
- `step.step_index`
- `step.step_path`
- `step.step_type`
- `action.status`

Optional but strongly recommended:

- `campaign_id`
- `scenario_id`
- `scenario_ref_id`
- `workflow_id`
- `account_platform`
- `account_label`
- `target_type`
- `target_id`
- `target_label`
- artifact ids
- `duration_ms`
- `error.code`
- `error.retryable`

## Event Taxonomy

Use stable event names. Do not create one-off strings in random modules.

Execution lifecycle:

- `execution.created`
- `execution.started`
- `execution.paused`
- `execution.resumed`
- `execution.cancelled`
- `execution.completed`
- `execution.failed`

Step lifecycle:

- `execution.step.started`
- `execution.step.completed`
- `execution.step.failed`
- `execution.step.retried`
- `execution.step.skipped`

Action-level events:

- `automation.action.started`
- `automation.action.completed`
- `automation.action.failed`
- `automation.action.skipped`

Artifact events:

- `artifact.captured`
- `artifact.persisted`
- `artifact.failed`

Account/device context:

- `account.session.checked`
- `account.session.failed`
- `device.reserved`
- `device.released`
- `device.health.changed`

Operator/DLQ:

- `dlq.opened`
- `dlq.retried`
- `dlq.closed`
- `operator.action.created`

## Write Path

Recommended write path:

```text
runtime action
  -> emit canonical execution event
  -> commit event
  -> outbox publishes SSE
  -> projection updates execution_steps / run summary
  -> artifact service saves screenshot/XML metadata
  -> DLQ service opens failure row if terminal
```

Important rule:

`execution_events` must be append-only. Do not update past events. Fixes and retries are new events.

## Read Path

Add one backend read model endpoint:

```text
GET /api/executions/{execution_id}/run-trace
```

Response shape:

```json
{
  "execution": {
    "execution_id": "uuid",
    "status": "running",
    "started_at": "...",
    "finished_at": null
  },
  "context": {
    "campaign_id": "uuid",
    "scenario_id": "uuid",
    "device_id": "uuid",
    "device_serial": "RF8...",
    "account_id": "uuid",
    "account_label": "masked"
  },
  "summary": {
    "total_steps": 25,
    "completed_steps": 12,
    "failed_steps": 0,
    "current_step_index": 13,
    "current_step_type": "social_action",
    "duration_ms": 123456,
    "counters": {
      "matched": 8,
      "liked": 5,
      "commented": 4,
      "skipped": 3,
      "errors": 0
    }
  },
  "steps": [],
  "timeline": [],
  "artifacts": [],
  "dlq": null
}
```

The UI should read this one endpoint for initial state, then subscribe to:

```text
GET /api/executions/{execution_id}/events/stream
```

SSE should only append new canonical events. The frontend should not need to query Temporal step logs to reconstruct business state.

## Unified UI Design

One screen: Campaign Monitor -> Run Trace.

Top summary:

- Campaign
- Scenario
- Phone serial
- Account
- Status
- Elapsed time
- Current step
- Counters

Main table:

| Time | Step | Phone | Account | Action | Target | Result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10:15:30 | 12 | RF8... | acc... | like | post keyword match | ok | screenshot/xml |

Right-side detail drawer:

- Full event JSON, redacted.
- Step config snapshot.
- Matched XML node and bounds.
- Before/after screenshot.
- Error reason and retry hint.
- Related DLQ entry if any.

Filters:

- Phone
- Account
- Step status
- Action type
- Target type
- Error only
- Has artifact
- Time range

This UI should not expose separate "Temporal log", "event log", "step rows", "DLQ log" names to the operator. Those are internal stores.

## Security And Privacy Rules

Never log:

- Passwords
- Cookies
- Access tokens
- TOTP seeds
- Full session payloads
- Raw credentials
- Large raw XML blobs inside event payloads

Prefer:

- Artifact IDs instead of inline screenshots/XML.
- Secret redaction at event emission boundary.
- `account_label` masked or operator-safe.
- `comment_template_id` or short preview instead of full sensitive content, unless the product explicitly needs the full emitted comment in audit storage.
- `payload_size_bytes` when large payloads are omitted.

## Performance Rules

For long runs such as 8 hours:

- Do not keep all detailed events in React state forever.
- Initial page loads from `/run-trace` with pagination.
- SSE appends only newest events.
- Step table should virtualize rows.
- Heavy artifacts stay in object storage and load on demand.
- Store counters as projections, not by scanning all events on every poll.
- Partition or index event storage by `org_id`, `execution_id`, `occurred_at`.
- Use retention policy: detailed events 30-90 days, summary longer.

Recommended indexes:

```sql
CREATE INDEX idx_execution_events_exec_time
ON execution_events (execution_id, occurred_at, id);

CREATE INDEX idx_execution_events_org_campaign_time
ON execution_events (org_id, campaign_id, occurred_at DESC);

CREATE INDEX idx_execution_events_device_time
ON execution_events (org_id, device_id, occurred_at DESC);

CREATE INDEX idx_execution_events_account_time
ON execution_events (org_id, account_id, occurred_at DESC);

CREATE INDEX idx_execution_events_step
ON execution_events (execution_id, step_index, occurred_at);
```

If `execution_events.payload` remains JSON only, add generated columns or explicit columns for high-cardinality filters such as `device_id`, `account_id`, `step_index`, and `event_name`. Do not depend on deep JSON filters for hot monitor screens.

## Implementation Recommendation For This Repo

Phase 1: Contract only

- Define `ExecutionEventEnvelopeV1`.
- Normalize field names: use `org_id` internally, keep `organization_id` only as API compatibility alias.
- Add account/device/step path fields to every step event.
- Add event taxonomy constants.
- Add redaction tests.

Phase 2: Backend read model

- Add `/api/executions/{execution_id}/run-trace`.
- Backend merges `execution_events`, `execution_steps`, `execution_artifacts`, `execution_dlq`, and execution/account/device metadata.
- UI receives one normalized response.

Phase 3: Frontend consolidation

- Campaign monitor cards still poll workflow list lightly.
- Expanded run trace uses `/run-trace` + SSE only.
- Remove business-state reconstruction from Temporal `/workflows/{workflow_id}/steps`.
- Keep Temporal progress only as fallback/runtime health.

Phase 4: Projection

- Add `execution_run_summaries` or use a materialized summary maintained by event projection.
- Counters become authoritative for long-running tasks.
- UI summary reads counters without scanning full timeline.

## Acceptance Criteria

A good log/monitoring implementation is accepted when an operator can answer these from one screen:

- Phone nào đang chạy?
- Account nào đang chạy?
- Đang ở campaign/scenario nào?
- Đang ở step index/path nào?
- Đã match target nào?
- Đã thực hiện action nào?
- Like/comment/request/skipped/error bao nhiêu?
- Có screenshot/XML chứng minh không?
- Nếu fail thì fail vì selector, account, device, network, hay scenario config?
- Có thể lọc theo phone/account/action/error trong một giao diện không?

## Sources

- https://opentelemetry.io/docs/specs/otel/logs/data-model/
- https://opentelemetry.io/docs/concepts/semantic-conventions/
- https://opentelemetry.io/docs/specs/semconv/resource/
- https://docs.cloud.google.com/logging/docs/structured-logging
- https://www.elastic.co/docs/reference/ecs
- https://www.elastic.co/docs/reference/ecs/ecs-tracing
- https://docs.temporal.io/develop/python/platform/observability
- https://docs.temporal.io/develop/typescript/platform/observability

## Unresolved Questions

- Should full comment text be audit-stored, or only a template ID/hash plus short preview?
- Should the first implementation add a physical `execution_run_summaries` table, or compute summary from existing rows first?
- Should account labels be visible to every operator, or restricted by account permissions?
