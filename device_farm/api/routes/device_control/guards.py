"""Shared guards for device-control routes.

Why this exists:
- Some scenario executions run in separate Temporal worker processes.
- The in-memory ``device._scenario_active`` counter is process-local, so the API/WS
  process may temporarily see 0 even while automation is driving the phone.
- We therefore consult Redis (when enabled) as a cross-process source of truth.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi.responses import JSONResponse

from runtime.core import DeviceState


async def _redis_scenario_active(serial: str) -> bool:
    try:
        from services import redis_store

        if not redis_store.enabled():
            return False
        r = redis_store.client()
        if r is None:
            return False
        v = await r.get(redis_store.key(f"device:{serial}:scenario_active"))
        return int(v or "0") > 0
    except Exception:
        return False


async def reject_manual_control_if_busy(device) -> Optional[JSONResponse]:
    """Reject manual control when a scenario or busy dispatcher owns the device."""
    is_busy_state = getattr(device, "state", None) == DeviceState.BUSY
    scenario_active_local = int(getattr(device, "_scenario_active", 0) or 0) > 0
    serial = getattr(device, "serial", "")
    scenario_active = scenario_active_local or await _redis_scenario_active(serial)
    if is_busy_state or scenario_active:
        try:
            from services.manual_takeover import is_manual_takeover_active

            if await is_manual_takeover_active(serial):
                return None
        except Exception:
            pass
    if not (is_busy_state or scenario_active):
        return None
    reason = "busy_state" if is_busy_state else "scenario_active"
    return JSONResponse(
        {
            "error": "device_busy",
            "reason": reason,
            "scenario_active": scenario_active,
        },
        status_code=409,
    )
