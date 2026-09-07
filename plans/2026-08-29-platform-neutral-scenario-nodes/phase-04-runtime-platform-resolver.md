# Phase 04 - Runtime Platform Resolver

## Goal

Runtime must resolve platform deliberately and trace the decision.

## Files To Modify

- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/social_actions.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/platform_session.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/extraction.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/steps/control_flow.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/social_ext/registry.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario/executor.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/u2_executor.py`

## Resolver Contract

```python
ResolvedPlatform = {
    "requested": "auto",
    "resolved": "facebook",
    "adapter": "facebook@2.0.0",
    "capability": "social.comments.open",
    "execution_mode": "generic_recipe | adapter_code",
    "facets": {"comment_surface": "overlay"},
    "reason_code": "resolved_from_scenario_platform",
}
```

## Resolution Order

1. Explicit step platform.
2. Scenario default platform.
3. Campaign target/account platform.
4. Org default platform.
5. If still unknown: fail validation/execution for social nodes.
6. If platform supports safe generic recipe: use recipe and emit trace.
7. If platform needs adapter code: dispatch to adapter and emit trace.
8. If unsupported: fail with actionable error.

## Specialization Rule

Use the least custom implementation that is safe:

1. Shared device primitive: tap, input, swipe, wait, extract.
2. Shared recipe: ordered primitives plus parameterized selectors.
3. Platform facet config: connection kind, content surface, community type.
4. Adapter code: only for dynamic/safety-critical behavior.

Facebook-specific code remains valid for Facebook, but never becomes the fallback execution path for other platforms.

## Error Codes

- `PLATFORM_REQUIRED`
- `PLATFORM_UNSUPPORTED`
- `CAPABILITY_UNSUPPORTED`
- `GENERIC_RECIPE_UNSAFE`
- `ADAPTER_REQUIRED`
- `ADAPTER_DOCTOR_FAILED`

## Acceptance

- No social handler uses `step.get("platform") or "facebook"` directly.
- All platform decisions pass through resolver.
- Trace/log/result include requested/resolved platform, execution mode, facets, and reason code.
- Existing Facebook scenarios still run because they already carry `platform: facebook` or are migrated.
- A TikTok/Instagram/Threads node never executes Facebook code because the requested capability is missing.
