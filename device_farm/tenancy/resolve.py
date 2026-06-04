"""Resolve default vs effective organization for multi-org users."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tenancy.context import get_current_org_id

if TYPE_CHECKING:
    from db.models import User


def get_user_default_org_id(user: Any) -> str | None:
    """Persisted default workspace (``users.default_org_id``)."""
    return (
        getattr(user, "default_org_id", None)
        or getattr(user, "org_id", None)  # legacy rows / tests
    )


def get_effective_org_id(user: Any | None = None) -> str | None:
    """Org for the current request: header/context first, then user default."""
    scoped = get_current_org_id()
    if scoped:
        return scoped
    if user is not None:
        return get_user_default_org_id(user)
    return None
