# Phase 02 - Capability Contract V2

## Goal

Make capability support explicit enough that frontend/runtime never assumes Facebook.

## Files To Modify

- `/Users/hoangle/farm/device-farm/device_farm/services/social_ext/contract.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/social_ext/registry.py`
- `/Users/hoangle/farm/device-farm/device_farm/services/social_ext/facebook.py`
- `/Users/hoangle/farm/device-farm/device_farm/api/routes/social_ext.py`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/services/social-ext-api.ts`

## Contract Additions

Add metadata, not new executor behavior yet:

```python
Capability = {
    "id": "social.comments.open",
    "step_types": ["social_open_comments"],
    "input_schema_version": 1,
    "output_schema_version": 1,
    "requires_account": False,
    "mutates_platform_state": False,
    "safe_generic_recipes": ["hierarchy_locator"],
    "facets": ["comment_surface", "locator_strategy"],
}
```

Adapter support example:

```python
PlatformSupport = {
    "platform": "facebook",
    "coverage": "L2 Active",
    "capabilities": {
        "social.comments.open": {
            "status": "active",
            "execution_mode": "adapter_code",
            "facets": {"comment_surface": "overlay"}
        },
        "social.connection.request": {
            "status": "active",
            "execution_mode": "adapter_code",
            "facets": {"connection_kind": "friend_request"}
        },
    },
}
```

## Required Behavior

- Registry response returns capabilities and step support in one request.
- Unknown platform means unsupported, not Facebook.
- Missing platform on social node means resolve from scenario/campaign default; if none, validation fails with actionable error.
- Draft platforms may exist but must not claim active support.
- Unsupported platform/capability never runs Facebook as a substitute.
- Capability can declare safe generic recipes so a platform can reuse behavior without custom code.
- Adapter code is required only for behavior that cannot be expressed by schema/config/recipe.

## Performance

- Capability matrix is static/cached; no per-node API fanout.
- Adapter metadata load must not perform device, DB, or network probes.
- Doctor/readiness checks are separate endpoints or execution preflight.

## Acceptance

- Backend can answer: "which platforms support this node/capability?"
- Backend can answer: "which behavior is generic recipe and which is platform-specific adapter code?"
- Frontend can answer without guessing.
- Existing Facebook support remains `L2 Active`.
- Draft platforms stay visible but disabled unless loaded with real support.
