"""Account graph size: record observations, answer "which playbook?".

An account with no friends and an account with five hundred need opposite
strategies. The first has no mutual-friend signal at all, so the platform's own
suggestions are strangers and working them earns ignored requests; the second is
exactly what those suggestions are built for. Routing between them needs one
number, which until now nobody measured.

Stage thresholds here are judgement, not measurement. They exist so the system
can route today; replace them with observed acceptance rates once there is
enough history to compute one.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account_graph_metric import AccountGraphMetric
from services.platform_readiness import DEFAULT_PLATFORM

STAGE_PREPARE = "prepare"
STAGE_SEED = "seed"
STAGE_TRANSITION = "transition"
STAGE_STEADY = "steady"

# Below SEED_CEILING the platform has no graph signal to offer, so candidates
# must come from shared context the account can manufacture itself (groups).
# Above STEADY_FLOOR its own suggestions are worth more than anything we can
# assemble. Between the two, both sources are useful.
_DEFAULT_SEED_CEILING = 20
_DEFAULT_STEADY_FLOOR = 50


def _bounded_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def seed_ceiling() -> int:
    return _bounded_env_int("ACCOUNT_STAGE_SEED_CEILING", _DEFAULT_SEED_CEILING)


def steady_floor() -> int:
    return _bounded_env_int("ACCOUNT_STAGE_STEADY_FLOOR", _DEFAULT_STEADY_FLOOR)


def stage_for_friend_count(friend_count: int | None) -> str:
    """Which playbook an account with this many friends should run.

    An unknown count is treated as the coldest case on purpose: assuming an
    account is warmer than it is means pointing it at suggestions that will not
    convert, which is the expensive mistake.
    """
    if friend_count is None:
        return STAGE_SEED
    if friend_count >= steady_floor():
        return STAGE_STEADY
    if friend_count >= seed_ceiling():
        return STAGE_TRANSITION
    return STAGE_SEED


async def record_graph_metric(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    platform: str,
    metric: str,
    value: int,
    source: str = "count_label",
    evidence: str | None = None,
    device_serial: str | None = None,
    execution_id: str | None = None,
    observed_at: datetime | None = None,
) -> AccountGraphMetric:
    row = AccountGraphMetric(
        id=str(uuid4()),
        org_id=org_id,
        account_id=account_id,
        platform=str(platform or DEFAULT_PLATFORM).strip().casefold(),
        metric=str(metric or "friends").strip().casefold(),
        value=max(0, int(value)),
        source=str(source or "count_label"),
        evidence=(evidence or None) and str(evidence)[:255],
        device_serial=device_serial or None,
        execution_id=execution_id or None,
        observed_at=observed_at or datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    return row


async def latest_graph_metric(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    metric: str = "friends",
) -> AccountGraphMetric | None:
    return (
        await db.execute(
            select(AccountGraphMetric)
            .where(
                AccountGraphMetric.org_id == org_id,
                AccountGraphMetric.account_id == account_id,
                AccountGraphMetric.metric == metric,
            )
            .order_by(AccountGraphMetric.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def graph_growth(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    metric: str = "friends",
    limit: int = 30,
) -> dict[str, Any]:
    """Newest and oldest observation in the window, and the delta between them.

    This is the answer to "is the scenario working" — a single reading cannot
    tell you that, which is why the table keeps history.
    """
    rows = list(
        (
            await db.execute(
                select(AccountGraphMetric)
                .where(
                    AccountGraphMetric.org_id == org_id,
                    AccountGraphMetric.account_id == account_id,
                    AccountGraphMetric.metric == metric,
                )
                .order_by(AccountGraphMetric.observed_at.desc())
                .limit(max(2, limit))
            )
        ).scalars()
    )
    if not rows:
        return {"metric": metric, "observations": 0, "latest": None, "delta": None}
    newest, oldest = rows[0], rows[-1]
    return {
        "metric": metric,
        "observations": len(rows),
        "latest": newest.value,
        "latest_at": newest.observed_at,
        "earliest": oldest.value,
        "earliest_at": oldest.observed_at,
        "delta": newest.value - oldest.value,
    }
