from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .enums import UserRole
from .utils import _now, _uuid, _api_key


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(String(64), unique=True, default=_api_key, index=True)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.OPERATOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Current organization used for request scoping.
    # Nullable for legacy rows before migration backfill.
    org_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    devices: Mapped[list["Device"]] = relationship("Device", back_populates="user")
    campaigns: Mapped[list["Campaign"]] = relationship("Campaign", back_populates="user")
    memberships: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="user", cascade="all, delete-orphan"
    )
    organization: Mapped[Optional["Organization"]] = relationship("Organization")

    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<User {self.email} role={self.role}>"

