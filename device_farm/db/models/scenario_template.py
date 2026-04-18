from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from .utils import _now, _uuid


class ScenarioTemplate(Base):
    """
    Shared scenario building block — reusable across campaigns.

    Reference in a scenario step:
        {"type": "run_scenario", "scenario_name": "<name>"}

    is_builtin=True templates cannot be deleted via API (system-owned).
    """

    __tablename__ = "scenario_templates"
    __table_args__ = (
        Index("idx_scenario_templates_name", "name"),
        Index("idx_scenario_templates_category", "category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="general")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    edges: Mapped[list] = mapped_column(JSON, default=list)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[str] = mapped_column(String(500), default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    def __repr__(self) -> str: 
        return f"<ScenarioTemplate {self.name} category={self.category}>"
