"""Synchronous bridge from scenario steps into the account-graph tables.

Same shape as `services/candidate_runtime.py`: scenario steps run on a worker
thread, the persistence layer is async, so each call hops through
`run_activity_coro_blocking`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from services.platform_readiness import DEFAULT_PLATFORM
from tenancy.context import tenant_context

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext


def record_connection_count(
    *,
    sc: "ScenarioContext",
    step: dict[str, Any],
    platform: str,
    metric: str,
    value: int,
    source: str = "count_label",
    evidence: str | None = None,
) -> dict[str, Any]:
    """Append one observation of this account's graph size."""
    from db.database import activity_session, run_activity_coro_blocking
    from services.account_actions import resolve_action_identity
    from services.account_actions.coordinator import _resolve_tenant
    from services.account_graph import record_graph_metric

    identity = resolve_action_identity(
        step=step,
        scenario=sc.scenario,
        variables=sc.ctx.get("vars", {}),
        execution_id=sc.execution_id,
        device_serial=sc.serial,
    )
    resolved_platform = str(platform or DEFAULT_PLATFORM).strip().casefold()

    async def record() -> dict[str, Any]:
        async with activity_session() as db:
            org_id, account_id, _, _ = await _resolve_tenant(
                db, identity, require_ids=False
            )
            with tenant_context(org_id):
                row = await record_graph_metric(
                    db,
                    org_id=org_id,
                    account_id=account_id,
                    platform=resolved_platform,
                    metric=metric,
                    value=value,
                    source=source,
                    evidence=evidence,
                    device_serial=sc.serial,
                    execution_id=sc.execution_id,
                )
                return {
                    "recorded": True,
                    "account_id": account_id,
                    "metric": row.metric,
                    "value": row.value,
                    "source": row.source,
                }

    return run_activity_coro_blocking(record())
