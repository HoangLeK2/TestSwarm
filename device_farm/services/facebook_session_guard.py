"""Facebook binding of the neutral session guard.

The logic lives in ``services/platform_session_guard.py``. This module keeps the
Facebook-named surface alive for existing callers; prefer the neutral names in
new code.
"""

from __future__ import annotations

from functools import partial

from services.device_platform_session import FACEBOOK_PLATFORM
from services.platform_session_guard import (
    PlatformSessionGuardDecision,
    PlatformSessionGuardMode,
    PlatformSessionGuardOutcome,
    guard_platform_session,
    observe_platform_readiness_for_device,
    platform_session_guard_mode,
    platform_session_live_probe_required,
)

FacebookSessionGuardMode = PlatformSessionGuardMode
FacebookSessionGuardOutcome = PlatformSessionGuardOutcome
FacebookSessionGuardDecision = PlatformSessionGuardDecision

facebook_session_guard_mode = platform_session_guard_mode
guard_facebook_session = partial(guard_platform_session, platform=FACEBOOK_PLATFORM)
facebook_session_live_probe_required = partial(
    platform_session_live_probe_required, platform=FACEBOOK_PLATFORM
)
observe_facebook_readiness_for_device = partial(
    observe_platform_readiness_for_device, platform=FACEBOOK_PLATFORM
)

__all__ = [
    "FacebookSessionGuardDecision",
    "FacebookSessionGuardMode",
    "FacebookSessionGuardOutcome",
    "facebook_session_guard_mode",
    "facebook_session_live_probe_required",
    "guard_facebook_session",
    "observe_facebook_readiness_for_device",
]
