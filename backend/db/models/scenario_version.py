"""Scenario version — immutable snapshot of a scenario at execution time."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now, _uuid


class ScenarioVersion(Base):
    """Immutable snapshot of a Scenario captured when an Execution starts.

    Each Execution references the exact version it ran against, so edits to
    the live Scenario after dispatch don't retroactively change history.
    """

    __tablename__ = "scenario_versions"
    __table_args__ = (
        UniqueConstraint("scenario_id", "version", name="uq_sv_scenario_version"),
        Index("idx_sv_scenario", "scenario_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Snapshot of scenario state at creation time
    steps: Mapped[list] = mapped_column(JSON, default=list)
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    edges: Mapped[list] = mapped_column(JSON, default=list)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    instructions: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    scenario: Mapped["Scenario"] = relationship("Scenario")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScenarioVersion scenario={self.scenario_id[:8]} v={self.version}>"
