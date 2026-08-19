"""Social platform extension contract and registry (Epic 08)."""

from services.social_ext.contract import (
    CONNECTION_KINDS,
    DEFAULT_CONNECTION_KIND,
    SOCIAL_ENTITIES,
    SOCIAL_STEP_TYPES,
)
from services.social_ext.registry import (
    SocialPlatformRegistry,
    connection_kind,
    get_social_platform_registry,
    supports_entity,
    supports_step,
)

__all__ = [
    "CONNECTION_KINDS",
    "DEFAULT_CONNECTION_KIND",
    "SOCIAL_ENTITIES",
    "SOCIAL_STEP_TYPES",
    "SocialPlatformRegistry",
    "connection_kind",
    "get_social_platform_registry",
    "supports_entity",
    "supports_step",
]
