# Phase 1 - Contract And Storage

Status: Pending
Priority: P1
Effort: 4h

## Objective

Define durable recovery policy contracts without creating a second scenario system.

## Key Decisions

- Recovery playbooks are existing org scenarios.
- Mark recovery playbooks with tag `recovery`; optionally add `incident:<type>` tags for filtering.
- Add `campaigns.recovery_policy JSON NOT NULL DEFAULT '{}'`.
- Keep `OrgScenario.kind` unchanged (`sequence` / `graph`) to avoid enum migration churn.
- Validate policy references against org-owned active org scenarios.

## Related Files

- `/Users/hoangle/farm/device-farm/device_farm/db/models/campaign.py`
- `/Users/hoangle/farm/device-farm/device_farm/db/migrations/086_campaign_recovery_policy.py`
- `/Users/hoangle/farm/device-farm/device_farm/api/schemas/campaign_entity.py`
- `/Users/hoangle/farm/device-farm/device_farm/api/schemas/campaign.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/campaign/service.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/campaign/scenario_ref_resolver.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/campaign/execution_runtime.py`
- `/Users/hoangle/farm/device-farm/device_farm/temporal/shared.py`

## Contract

Create backend schema models:

- `RecoveryPolicy`
- `RecoveryRule`
- `RecoverySuccessCheck`

Allowed incident types for MVP:

- `app_popup`
- `facebook_popup`
- `profile_page`
- `lost_post_detail`
- `comment_panel_closed`
- `stuck_screen`
- `login_or_checkpoint`
- `unknown`

Allowed outcomes:

- `retry_step`
- `continue`
- `fail`
- `pause_for_takeover`
- `open_dlq`

## Implementation Steps

1. Add migration for `campaigns.recovery_policy`.
2. Add model field to `Campaign`.
3. Add Pydantic schemas for create/update/out.
4. Validate policy shape in service layer, not only frontend.
5. Validate referenced `scenario_id` exists, is active or draft as allowed, belongs to the org, and has runnable body.
6. Include recovery policy in dispatch metadata and `ScenarioInput.scenario_config`.
7. Add compatibility fallback: missing or `{}` policy means disabled.

## Edge Cases

- Referenced scenario archived after campaign setup: dispatch should fail with clear `RECOVERY_SCENARIO_NOT_FOUND`.
- Rule points to the same main scenario: allow only if call stack does not recurse; normal `run_scenario` circular guard still applies.
- Empty rules with enabled true: valid but no-op with warning in validation.
- Recovery scenario with `clear_app` / `stop_app`: allowed but monitor must show it; no hidden destructive behavior.

## Tests

- Migration adds default `{}` and does not break existing campaign rows.
- Campaign create/update round trips `recovery_policy`.
- Invalid scenario reference is rejected.
- Archived scenario reference is rejected.
- Dispatch passes policy into `ScenarioInput.scenario_config`.

## Success Criteria

- Users can save a campaign-level recovery policy.
- Existing campaigns run unchanged.
- No new org scenario kind is required.
