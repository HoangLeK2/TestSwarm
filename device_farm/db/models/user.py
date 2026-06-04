from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from tenancy.context import get_current_org_id, set_current_org_id
from .enums import SystemUserRole
from .utils import _now, _uuid, _api_key


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(String(64), unique=True, default=_api_key, index=True)
    # Platform-wide role only (superadmin / support / system). Org RBAC uses organization_members.role.
    role: Mapped[str] = mapped_column(String(20), default=SystemUserRole.SYSTEM)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    default_org_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_failed_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    devices: Mapped[list["Device"]] = relationship("Device", back_populates="user")
    campaigns: Mapped[list["Campaign"]] = relationship(
        "Campaign",
        back_populates="user",
        foreign_keys="Campaign.user_id",
    )
    memberships: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="user", cascade="all, delete-orphan"
    )
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        foreign_keys=[default_org_id],
    )

    @hybrid_property
    def org_id(self) -> str | None:  # noqa: D102 — request-scoped effective org
        """Effective org for this request (header/context), else default workspace."""
        return get_current_org_id() or self.default_org_id

    @org_id.expression  # type: ignore[misc]
    @classmethod
    def org_id(cls):  # noqa: N805
        return cls.default_org_id

    @org_id.setter
    def org_id(self, value: str | None) -> None:
        """Tests and legacy code: set request tenant context (not persisted default)."""
        set_current_org_id(value)

    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<User {self.email} role={self.role}>"

