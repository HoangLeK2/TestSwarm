from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now, _uuid


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    business_logo: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    slug: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    plan: Mapped[str] = mapped_column(
        String(20), nullable=False, default="standard", server_default="standard"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        server_default="CURRENT_TIMESTAMP",
    )

    # Webhook config: POST to webhook_url on task complete/failed events.
    # webhook_events: comma-separated list e.g. "task.complete,task.failed"
    webhook_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    webhook_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    webhook_events: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="task.failed")

    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<Organization {self.business_name}>"


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner | member | supervisor
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="memberships")

