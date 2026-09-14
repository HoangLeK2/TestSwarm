"""ExecutionEvent — durable outbox + 30-day archive for execution domain events (DF-T-04-013)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from .utils import _now, _uuid


class ExecutionEvent(Base):
    """Append-only execution event store. Rows with ``published_at IS NULL`` are outbox pending."""

    __tablename__ = "execution_events"
    __table_args__ = (
        Index("idx_execution_events_exec_id", "execution_id", "id"),
        Index("idx_execution_events_org_type", "org_id", "event_type", "occurred_at"),
        Index("idx_execution_events_execution_time", "execution_id", "occurred_at"),
        Index(
            "idx_execution_events_outbox",
            "occurred_at",
            postgresql_where=text("published_at IS NULL"),
        ),
        Index(
            "idx_execution_events_outbox_lease",
            "publish_claimed_at",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
        # "What did this account do, in order" — the first question asked after
        # an account is banned. The identity used to live only inside the JSON
        # payload, so no index could serve it and the question had no answer.
        # See migration 131.
        Index(
            "idx_execution_events_org_account_time",
            "org_id",
            "account_id",
            "occurred_at",
        ),
        # Locates one step inside the scenario tree, loop iteration included.
        Index("idx_execution_events_exec_path", "execution_id", "step_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    execution_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Promoted out of payload.trace so they can be indexed and filtered on.
    # Nullable: events that predate migration 131 keep NULL, and lifecycle
    # events that belong to no account legitimately have none.
    account_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    device_serial: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Full position in the scenario tree, e.g. "0/login.else/zON2.then/RVeOb".
    step_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    publish_claim_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    publish_claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_envelope(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.isoformat(),
            "organization_id": self.org_id,
            "org_id": self.org_id,
            "campaign_id": self.campaign_id,
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "account_id": self.account_id,
            "device_serial": self.device_serial,
            "step_path": self.step_path,
            "payload": self.payload or {},
            "tags": _tags_for_type(self.event_type),
        }


def _tags_for_type(event_type: str) -> list[str]:
    parts = event_type.split(".")
    tags: list[str] = []
    for i in range(1, len(parts) + 1):
        tags.append(".".join(parts[:i]))
    return tags
