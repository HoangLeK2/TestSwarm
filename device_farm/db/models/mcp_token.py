from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from .utils import _now


class McpToken(Base):
    __tablename__ = "mcp_tokens"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_value: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scope_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    org_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
