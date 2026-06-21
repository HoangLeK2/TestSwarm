# Phase 4 - UI And Monitor

Status: Pending
Priority: P1
Effort: 5h

## Objective

Let users attach recovery scenarios to campaigns and see incident handling clearly during runs.

## Related Files

- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/services/api.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/types.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/create-campaign-dialog.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/edit-campaign-entity-dialog.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/campaign-org-scenario-picker.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/lib/execution-event-utils.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/workflow-step-list.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/campaign-monitor/workflow-progress-card.tsx`
- `/Users/hoangle/farm/device-farm/front-end/messages/vi.json`
- `/Users/hoangle/farm/device-farm/front-end/messages/en.json`

## Campaign Setup UX

Add a campaign section: `Kịch bản xử lý sự cố`.

Controls:

- Enable/disable recovery.
- Add rule.
- Incident type multi-select.
- Pick recovery scenario from org scenarios tagged `recovery`.
- Max attempts.
- Success checks.
- Outcome on success.
- Outcome on failure.

Keep the initial UI compact; advanced JSON editor is acceptable behind a disclosure for early rollout.

## Scenario Library UX

- Add filter chip for `recovery` scenarios.
- Add action/copy to mark scenario as recovery.
- Do not create a separate recovery-scenario CRUD surface.

## Monitor UX

Add event family rendering:

- `incident.detected`
- `incident.recovery.started`
- `incident.recovery.completed`
- `incident.resolved`
- `incident.failed`

Display per incident:

- Incident type and confidence.
- Original step index/type.
- Recovery scenario name.
- Attempt count.
- Outcome.
- Short evidence text.
- Link or inline thumbnail if screenshot artifact exists later.

## Event Folding

Extend `foldEventsToStepLog` without breaking existing step rows:

- Keep step rows as the primary list.
- Attach incident events to the relevant step row under `details.incidents`.
- If a recovery happens between steps, show a compact nested block below the current step.

## i18n

Add Vietnamese copy first-class; avoid mixed English/Vietnamese strings.

Core labels:

- `Kịch bản xử lý sự cố`
- `Loại sự cố`
- `Kịch bản phục hồi`
- `Thử lại bước hiện tại`
- `Chờ tiếp quản`
- `Đưa vào DLQ`

## Tests

- Policy form serializes backend-safe JSON.
- Scenario picker filters `recovery` tag.
- Event folding attaches incident events to step rows.
- Monitor renders resolved and failed incident timelines.
- Long labels fit mobile width.

## Success Criteria

- User can configure recovery without inserting nodes into the main flow.
- Operator can explain exactly why recovery ran and what it did.
- Existing campaign monitor behavior is unchanged when no incident events exist.
