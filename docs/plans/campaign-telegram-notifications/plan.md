# Spec: Campaign Telegram Notifications

## Objective
Extend campaign notifications so Telegram can tell an operator:

- which campaign is running or has finished
- what failed when a campaign fails
- when the campaign completes
- how many saved content items were collected

Use the existing notification pipeline rather than a Telegram-only branch. The same rendered event should continue to work for in-app, Slack, email, and webhook channels unless a later slice adds channel-specific formatting.

## Assumptions
- `campaign.dispatched`, `campaign.completed`, and `campaign.failed` are the canonical lifecycle events.
- "Collected data" means saved `ContentItem` rows associated with the campaign or its executions after dedupe.
- Start notification maps to dispatch/running state, not every per-device workflow start.
- Failure notification is campaign-level terminal failure; per-execution failure remains covered by DLQ/task events.
- Telegram delivery keeps using `NotificationService._send_telegram()` with the rendered `title` and `body`.

## Current Code Surface
- `device_farm/services/notification_events.py`
  - Parses domain events and renders templates.
  - Already knows `campaign.dispatched`, `campaign.completed`, `campaign.failed`.
  - Current campaign templates only render summary and deep link.
- `device_farm/services/notification_service.py`
  - Fans out notifications to in-app, Telegram, email, Slack, webhook.
  - Telegram sends `title + body` as plain text.
- `device_farm/services/campaign/events.py`
  - Logs campaign activity and dispatches webhooks.
  - Does not currently call `NotificationService.emit()`.
- `device_farm/services/campaign/lifecycle.py`
  - Emits `campaign.status.changed` after campaign status transitions.
- `device_farm/services/campaign/aggregator.py`
  - Computes terminal `COMPLETED` or `FAILED` state from execution counts and open DLQ count.
- `device_farm/temporal/activities.py`
  - Persists per-device execution results and opens DLQ on failed workflow finalization.
- `device_farm/db/crud/content.py`
  - Has `count_by_execution()`, but no campaign-level content count helper yet.

## Event Contract
Campaign notification events should carry this payload shape:

```python
{
    "type": "campaign.completed",
    "org_id": "org-1",
    "campaign_id": "camp-1",
    "resource_name": "Facebook comment crawl",
    "summary": "Campaign completed with 128 collected items",
    "status": "completed",
    "collected_count": 128,
    "execution_total": 4,
    "execution_completed": 4,
    "execution_failed": 0,
    "error_message": None,
}
```

Failure payloads should include `error_message` or `reason`:

```python
{
    "type": "campaign.failed",
    "org_id": "org-1",
    "campaign_id": "camp-1",
    "resource_name": "Facebook comment crawl",
    "summary": "Campaign failed: executions_failed",
    "status": "failed",
    "collected_count": 37,
    "execution_total": 4,
    "execution_completed": 1,
    "execution_failed": 3,
    "error_message": "executions_failed",
}
```

Dispatch payloads should include campaign name and initial execution totals when available:

```python
{
    "type": "campaign.dispatched",
    "org_id": "org-1",
    "campaign_id": "camp-1",
    "resource_name": "Facebook comment crawl",
    "summary": "Campaign dispatched to 4 executions",
    "status": "running",
    "execution_total": 4,
}
```

## Message Contract
The rendered Telegram text should be concise and operational:

```text
Campaign Facebook comment crawl completed
Status: completed
Collected: 128 items
Executions: 4 completed, 0 failed
Open: https://.../campaigns/camp-1
```

Failure example:

```text
Campaign Facebook comment crawl failed
Status: failed
Error: executions_failed
Collected: 37 items
Executions: 1 completed, 3 failed
Open: https://.../campaigns/camp-1
```

## Implementation Plan
1. Notification rendering slice - done
   - Extend `notification_events.py` context and templates with `status`, `collected_count`, `execution_completed`, `execution_failed`, `error_message`.
   - Keep missing values readable, for example `0` for counts and `unknown` for absent status.
   - Add focused unit tests in `device_farm/tests/test_epic09_notifications_analytics.py`.

2. Campaign event emission slice - done
   - Add a campaign notification emission helper near `services/campaign/events.py`.
   - Map `campaign.status.changed` transitions:
     - `running` or dispatch source -> `campaign.dispatched`
     - `completed` -> `campaign.completed`
     - `failed` -> `campaign.failed`
   - Include `resource_name` from the campaign row.
   - Queue notification payloads on the SQLAlchemy session and deliver them from an `after_commit` bounded background queue so Telegram/webhook fanout does not hold the campaign lifecycle transaction or spawn unbounded tasks.

3. Collection count slice - done
   - Add a campaign-level count helper that counts saved `ContentItem` rows attached to the campaign.
   - Use that count in terminal `campaign.completed` and `campaign.failed` payloads.

4. Delivery verification slice
   - Test Telegram by mocking `httpx.AsyncClient` or `_send_telegram`.
   - Assert the Telegram text includes campaign name, status, error for failures, and collected count.

## Testing Strategy
- Unit test `parse_domain_event()` and `render_notification()` for campaign dispatched, completed, and failed payloads.
- Unit test template linting remains clean.
- Integration-level test campaign transition emits a notification without hitting Telegram network.
- Existing Telegram test draft coverage remains unchanged.

Recommended focused commands:

```bash
pytest device_farm/tests/test_epic09_notifications_analytics.py -q
pytest device_farm/tests/test_notification_channel_draft_test.py -q
python -m py_compile device_farm/services/notification_events.py device_farm/services/notification_service.py device_farm/services/campaign/events.py
```

## Boundaries
- Always: reuse `NotificationService.emit()` / `notify()` and existing channel preferences.
- Always: preserve org scoping and tenant context.
- Always: keep Telegram tests network-free.
- Ask first: changing database schema, adding dependencies, or changing Telegram parse mode/formatting.
- Never: add a separate Telegram-only campaign notification path that bypasses notification preferences.

## Success Criteria
- A campaign start/dispatch notification includes the campaign name and running/dispatched status.
- A campaign failed notification includes campaign name, failure reason/error, collected count, and deep link.
- A campaign completed notification includes campaign name, completion status, collected count, and deep link.
- Telegram channel receives the same rendered title/body as the notification pipeline.
- Existing notification event tests and Telegram draft tests pass.

## Open Questions
- Should collected count be scoped to all saved campaign content, or only content from the latest execution batch?
- Should a partially successful campaign with open DLQ but some completed executions notify as completed, failed, or completed-with-warnings?
- Should Telegram eventually use Markdown formatting, or stay plain text for maximum compatibility?
