from __future__ import annotations

import threading

from services.social_actions.contract import SocialActionAdapter
from services.social_actions.facebook import FacebookSocialActionAdapter

_ADAPTERS: dict[str, SocialActionAdapter] = {
    "facebook": FacebookSocialActionAdapter(),
}
_LOCK = threading.RLock()


def register_social_action_adapter(
    adapter: SocialActionAdapter,
    *,
    replace: bool = False,
) -> None:
    """Register a platform adapter without changing generic scenario nodes."""

    global _ADAPTERS
    platform = (adapter.platform or "").strip().casefold()
    if not platform:
        raise ValueError("social action adapter platform is required")
    with _LOCK:
        if platform in _ADAPTERS and not replace:
            raise ValueError(f"social action adapter already registered: {platform}")
        updated = dict(_ADAPTERS)
        updated[platform] = adapter
        _ADAPTERS = updated


def unregister_social_action_adapter(platform: str) -> None:
    global _ADAPTERS
    clean = (platform or "").strip().casefold()
    with _LOCK:
        if clean == "facebook":
            raise ValueError("the built-in facebook adapter cannot be unregistered")
        updated = dict(_ADAPTERS)
        updated.pop(clean, None)
        _ADAPTERS = updated


def get_social_action_adapter(platform: str) -> SocialActionAdapter | None:
    """Return the adapter without coupling scenario node names to a platform."""

    return _ADAPTERS.get((platform or "").strip().casefold())
