# Phase 2 - Incident Detection Runtime

Status: Pending
Priority: P1
Effort: 5h

## Objective

Detect recoverable execution incidents from current device state and step results using pure, testable helpers.

## Related Files

- `/Users/hoangle/farm/device-farm/device_farm/services/execution/incident_detection.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/context.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/utils.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/extraction.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/extra_data/parsers/facebook/post_open_pipeline.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/extra_data/parsers/facebook/comment_pipeline.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/extra_data/collector.py`

## Design

Add a backend detector service with no direct persistence:

```python
ScreenSnapshot(
    xml: str | None,
    screenshot_b64: str | None,
    package_name: str | None,
    activity_name: str | None,
    hierarchy_hash: str | None,
)

Incident(
    type: str,
    confidence: float,
    reason_code: str,
    evidence: dict,
)
```

Detection sources:

- Pre-step snapshot for sensitive step types: `extract`, `fb_tap_comment_button`, `tap_fb_comment_button`, `wait_element`, `tap_selector`.
- Post-failure snapshot after a step fails or times out.
- Step result diagnostics from `edge_extra_summary`, `reason_code`, `details`, and comment scroll no-growth data.

## MVP Detector Rules

- `facebook_popup`: XML text/buttons such as notification prompts, contacts sync, save login, rate dialog, permission prompt.
- `app_popup`: Android permission/dialog chrome or known close/OK/Not now nodes.
- `profile_page`: Facebook profile layout markers such as Add friend, Message, profile header/avatar chips.
- `lost_post_detail`: expected post-detail/comment context missing before `fb_comments`.
- `comment_panel_closed`: comment sheet markers absent after opening comment target.
- `stuck_screen`: repeated hierarchy hash/no new comments after a bounded attempt.
- `login_or_checkpoint`: login, checkpoint, CAPTCHA, locked account; marked non-auto-safe by default.

## Guardrails

- Do not fire recovery while another device action is running.
- Do not call LLM/vision in MVP; XML/text heuristics are enough and cheaper.
- Do not classify login/checkpoint as safe.
- Keep detector confidence; only auto-run rules at `confidence >= 0.7`.
- Never mutate `ScenarioContext.ctx` inside detector.

## Implementation Steps

1. Add snapshot capture helper with bounded XML timeout and optional screenshot off by default.
2. Add detector registry keyed by incident type.
3. Reuse existing Facebook parser helpers where possible, especially post-detail and comment-sheet checks.
4. Attach `incident_candidates` to failed step results for audit.
5. Add metrics counters by `incident_type`, `confidence_bucket`, and `source`.
6. Keep `_auto_dismiss_popup` unchanged initially; this phase only detects.

## Tests

- Unit fixtures for XML popup, profile page, post detail, comment sheet, checkpoint.
- Detector returns no incident on normal post detail and normal comment sheet.
- Detector respects confidence threshold.
- Snapshot failures degrade to `unknown`, not exceptions.

## Success Criteria

- Runtime can classify the common popup/profile/lost-context cases without changing behavior.
- Detector is deterministic and fixture-testable.
- No new device taps are introduced in this phase.
