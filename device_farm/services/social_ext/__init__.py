"""Social platform extension contract and registry (Epic 08)."""

from services.social_ext.contract import SOCIAL_ENTITIES, SOCIAL_STEP_TYPES
from services.social_ext.registry import (
    SocialPlatformRegistry,
    get_social_platform_registry,
    supports_entity,
    supports_step,
)

__all__ = [
    "SOCIAL_ENTITIES",
    "SOCIAL_STEP_TYPES",
    "SocialPlatformRegistry",
    "get_social_platform_registry",
    "supports_entity",
    "supports_step",
]
