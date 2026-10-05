"""Map legacy scenario/content_type names to platform-qualified registry codes (DF-T-06-001)."""
from __future__ import annotations

from typing import Any

_STATIC_LEGACY_MAP: dict[str, str] = {}

_STRATEGY_DEFAULTS: dict[str, str] = {
    "ig_posts": "ig_media",
    "ig_comments": "ig_comment",
    "tiktok_posts": "tiktok_video",
    "tiktok_comments": "tiktok_comment",
    "threads_posts": "threads_post",
    "threads_comments": "threads_comment",
}

_PLATFORM_GENERIC_MAP: dict[str, dict[str, str]] = {
    "instagram": {
        "post": "ig_media",
        "media": "ig_media",
        "comment": "ig_comment",
    },
    "tiktok": {
        "post": "tiktok_video",
        "video": "tiktok_video",
        "comment": "tiktok_comment",
    },
    "threads": {
        "post": "threads_post",
        "thread": "threads_post",
        "comment": "threads_comment",
    },
}

_NESTED_STEP_KEYS = ("steps", "then", "else")


def _platform_for_strategy(strategy: str | None, platform: str | None) -> str | None:
    if platform:
        return str(platform).strip().lower()
    if not strategy:
        return None
    s = strategy.lower()
    if s.startswith("ig_"):
        return "instagram"
    if s.startswith("tiktok_"):
        return "tiktok"
    if s.startswith("threads_"):
        return "threads"
    return None


def qualify_content_type(
    content_type: str | None,
    *,
    platform: str | None = None,
    strategy: str | None = None,
) -> str | None:
    """Return platform-qualified content_type, or the original when no mapping applies."""
    if not content_type:
        if strategy and strategy in _STRATEGY_DEFAULTS:
            return _STRATEGY_DEFAULTS[strategy]
        return None

    normalized = str(content_type).strip().lower()
    if not normalized:
        return None

    if normalized in _STATIC_LEGACY_MAP:
        return _STATIC_LEGACY_MAP[normalized]

    # Already platform-qualified (tiktok_video, threads_post, …).
    if "_" in normalized:
        return normalized

    plat = _platform_for_strategy(strategy, platform)
    if plat:
        mapped = _PLATFORM_GENERIC_MAP.get(plat, {}).get(normalized)
        if mapped:
            return mapped

    if strategy and strategy in _STRATEGY_DEFAULTS:
        return _STRATEGY_DEFAULTS[strategy]

    return normalized


def default_content_type_for_entity(
    entity: str,
    platform: str,
    step: dict[str, Any] | None = None,
) -> str:
    """Content type for an ``(entity, platform)`` pair, honouring an explicit override.

    ``platform="auto"`` means the parser is picked from the app on screen, so the
    concrete type is only known at ingest time — the generic entity name is
    returned and agent-boot qualifies it.
    """
    step = step or {}
    plat = (platform or "").strip().lower()
    explicit = step.get("content_type")
    if explicit:
        qualified = qualify_content_type(str(explicit), platform=plat or None)
        return qualified or str(explicit)

    if entity == "text_nodes":
        return "text"
    if not plat or plat == "auto":
        return entity.rstrip("s") if entity.endswith("s") else entity

    generic = _PLATFORM_GENERIC_MAP.get(plat, {})
    singular = entity[:-1] if entity.endswith("s") else entity
    mapped = generic.get(singular)
    if mapped:
        return mapped
    return f"{plat}_{singular}"


def default_content_type_for_strategy(strategy: str, step: dict[str, Any] | None = None) -> str:
    """Infer platform-qualified default when a step omits content_type."""
    step = step or {}
    explicit = step.get("content_type")
    if explicit:
        return qualify_content_type(
            str(explicit),
            platform=step.get("platform"),
            strategy=strategy,
        ) or str(explicit)

    if strategy in _STRATEGY_DEFAULTS:
        return _STRATEGY_DEFAULTS[strategy]
    if strategy == "text_nodes":
        return "text"
    return qualify_content_type(
        "post",
        platform=step.get("platform"),
        strategy=strategy,
    ) or "post"


def migrate_content_type_in_step(step: dict[str, Any]) -> bool:
    """Rewrite legacy content_type on one step dict (in-place). Returns True if changed."""
    if not isinstance(step, dict):
        return False

    changed = False
    ctype = step.get("content_type")
    if isinstance(ctype, str):
        qualified = qualify_content_type(
            ctype,
            platform=step.get("platform") if isinstance(step.get("platform"), str) else None,
            strategy=step.get("strategy") if isinstance(step.get("strategy"), str) else None,
        )
        if qualified and qualified != ctype:
            step["content_type"] = qualified
            changed = True

    for key in _NESTED_STEP_KEYS:
        nested = step.get(key)
        if isinstance(nested, list):
            for child in nested:
                if isinstance(child, dict) and migrate_content_type_in_step(child):
                    changed = True
    return changed


def migrate_content_type_in_steps(steps: list[Any] | None) -> bool:
    """Migrate a top-level steps array. Returns True if any step changed."""
    if not isinstance(steps, list):
        return False
    changed = False
    for step in steps:
        if isinstance(step, dict) and migrate_content_type_in_step(step):
            changed = True
    return changed


def migrate_content_type_in_json(payload: dict[str, Any] | None) -> bool:
    """Migrate legacy content_type values inside scenario JSON blobs."""
    if not isinstance(payload, dict):
        return False
    changed = False
    if migrate_content_type_in_steps(payload.get("steps")):
        changed = True
    body = payload.get("body_json")
    if isinstance(body, dict) and migrate_content_type_in_json(body):
        changed = True
    return changed
