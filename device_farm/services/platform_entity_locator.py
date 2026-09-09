"""Platform-neutral defaults for locating an external entity on screen.

Same shape as ``services/platform_readiness.py``: the neutral fallback lives
here, the per-platform knowledge (how a Facebook group row is labelled) lives in
``services/<platform>_entity_locator.py`` and registers itself.

Adding a platform = add that module and call :func:`register_entity_locator`.
Nothing in the campaign dispatcher changes.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class EntityLocatorDefaults:
    """Selector defaults used when the entity carries no stored locator."""

    selector_by: str
    selector_value: str
    fallback_by: str
    fallback_value: str
    search_query: str
    extra_vars: Mapping[str, str] = field(default_factory=dict)


EntityLocatorResolver = Callable[[Any], EntityLocatorDefaults]

_RESOLVERS: dict[str, EntityLocatorResolver] = {}


def register_entity_locator(platform: str, resolver: EntityLocatorResolver) -> None:
    _RESOLVERS[(platform or "").strip().casefold()] = resolver


def neutral_entity_locator(entity: Any) -> EntityLocatorDefaults:
    name = entity.display_name
    return EntityLocatorDefaults(
        selector_by="text",
        selector_value=name,
        fallback_by="textContains",
        fallback_value=name,
        search_query=name,
    )


def resolve_entity_locator(entity: Any) -> EntityLocatorDefaults:
    key = (getattr(entity, "platform", "") or "").strip().casefold()
    if key and key not in _RESOLVERS:
        try:
            importlib.import_module(f"services.{key}_entity_locator")
        except ImportError:
            pass
    resolver = _RESOLVERS.get(key, neutral_entity_locator)
    return resolver(entity)
