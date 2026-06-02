"""Social platform extension contract and registry (Epic 08)."""

from services.social_ext.registry import (
    SocialPlatformRegistry,
    get_social_platform_registry,
)

__all__ = ["SocialPlatformRegistry", "get_social_platform_registry"]
