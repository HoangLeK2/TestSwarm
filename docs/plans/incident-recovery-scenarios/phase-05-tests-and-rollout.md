# Phase 5 - Tests And Rollout

Status: Pending
Priority: P1
Effort: 2h

## Objective

Ship recovery safely with targeted regression coverage and a cautious rollout path.

## Test Matrix

Backend:

- Policy validation.
- Scenario registry includes recovery scenarios.
- Fallback executor recovery success and failure.
- Temporal batch path with recovery enabled.
- Pause/cancel during recovery.
- DLQ outcome.
- Existing campaign without recovery policy unchanged.

Agent/collector-adjacent:

- Facebook popup XML fixtures.
- Facebook profile page XML fixtures.
- Post-detail and comment-sheet detection fixtures.
- Stuck/no-growth diagnostics mapped to incidents.

Frontend:

- Form serialization.
- Event fold/render.
- i18n coverage.
- Mobile layout smoke.

## Manual Verification

Use a real Facebook test account/device:

1. Create recovery scenario `Đóng popup Facebook`.
2. Add campaign rule `facebook_popup -> Đóng popup Facebook -> retry_step`.
3. Trigger notification/contact popup.
4. Confirm monitor shows detected -> recovery started -> resolved -> crawl resumed.
5. Trigger profile misnavigation.
6. Confirm configured `Back về bài viết` recovery runs or pauses for takeover.
7. Trigger login/checkpoint.
8. Confirm system does not auto-click through; it pauses or opens DLQ.

## Rollout Strategy

- Feature defaults off.
- Enable per campaign only.
- Start with popup/profile incidents.
- Add stuck-screen and comment-panel incidents after popup path is proven.
- Keep event payloads stable before exposing analytics.

## Observability

Metrics:

- `execution_incidents_detected_total{type}`
- `execution_recovery_attempts_total{rule_id,outcome}`
- `execution_recovery_duration_seconds{rule_id}`
- `execution_recovery_budget_exhausted_total{rule_id}`

Logs:

- One compact structured line per incident and recovery attempt.
- Include execution id, device serial, step index, incident type, rule id, outcome, duration.

## Rollback

- Disable policy on campaign.
- Server treats missing/disabled policy as no-op.
- Event UI ignores unknown incident events.
- Migration is additive and safe to leave in place.

## Success Criteria

- No recovery activity occurs unless policy is enabled.
- Recovery does not hide login/checkpoint/account-risk states.
- Crawl context remains correct after recovery.
- Operator sees evidence for every automatic recovery.
