from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


class TenantScopedModel:
    """Mixin for tables that must be tenant-isolated by organization.

    Any ORM query that selects a TenantScopedModel will be automatically
    constrained by the active `current_org_id` (see `tenancy.sqlalchemy`).
    """

    __abstract__ = True

    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

