"""Observations of how large an account's social graph is.

Append-only on purpose. The question worth answering is "is this account
growing, and how fast", which needs a series rather than a current value — and
a bad read can never overwrite a good one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid

# Platform-neutral vocabulary: a follow graph and a friend graph are the same
# measurement with a different name.
GRAPH_METRICS = ("friends", "followers", "following")


class AccountGraphMetric(TenantScopedModel, Base):
    __tablename__ = "account_graph_metrics"
    __table_args__ = (
        Index(
            "idx_account_graph_metrics_latest",
            "org_id",
            "account_id",
            "metric",
            "observed_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    # How the number was obtained. "empty_state" means Facebook showed a
    # "no friends to show" sentence instead of a count — a real zero, not a
    # failed read, and worth being able to tell apart later.
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="count_label"
    )
    evidence: Mapped[Optional[str]] = mapped_column(String(255))
    device_serial: Mapped[Optional[str]] = mapped_column(String(128))
    execution_id: Mapped[Optional[str]] = mapped_column(String(36))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
