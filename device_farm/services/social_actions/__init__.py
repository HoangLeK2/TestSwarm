"""Reusable social action contracts and platform adapters."""

from services.social_actions.registry import (
    get_social_action_adapter,
    register_social_action_adapter,
    unregister_social_action_adapter,
)

__all__ = [
    "get_social_action_adapter",
    "register_social_action_adapter",
    "unregister_social_action_adapter",
]
