"""How a Facebook entity is located on screen.

A group row in the Facebook app carries the group name in its content
description followed by a comma and the member/activity blurb ("Group One,
12K members"), so the name is a description *prefix*, never the full text.
"""

from __future__ import annotations

from typing import Any

from services.platform_entity_locator import (
    EntityLocatorDefaults,
    neutral_entity_locator,
    register_entity_locator,
)


def resolve_facebook_entity_locator(entity: Any) -> EntityLocatorDefaults:
    if entity.entity_type != "group":
        return neutral_entity_locator(entity)
    name = entity.display_name
    return EntityLocatorDefaults(
        selector_by="descriptionStartsWith",
        selector_value=f"{name},",
        fallback_by="descriptionContains",
        fallback_value=name,
        search_query=name,
        extra_vars={"GROUP_NAME": name, "TARGET_GROUP_NAME": name},
    )


register_entity_locator("facebook", resolve_facebook_entity_locator)
