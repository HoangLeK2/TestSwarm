"""Per-tenant operational settings (DF-T-02-005)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base

DEFAULT_DEAD_THRESHOLD_SEC = 600

DEFAULT_SESSION_IDLE_THRESHOLDS: dict[str, int] = {
    "manual": 300,
    "scenario": 60,
    "mcp": 120,
}


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
    session_idle_thresholds: Mapped[dict | None] = mapped_column(JSON, nullable=True)
