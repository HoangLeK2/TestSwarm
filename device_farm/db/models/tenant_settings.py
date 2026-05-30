"""Per-tenant operational settings (DF-T-02-005)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base

DEFAULT_DEAD_THRESHOLD_SEC = 600


class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dead_threshold_sec: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_DEAD_THRESHOLD_SEC,
        server_default="600",
    )
