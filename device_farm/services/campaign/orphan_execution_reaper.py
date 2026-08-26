"""Background worker — settle executions whose Temporal workflow is gone.

An execution row and the workflow that drives it are two separate facts, and
they can disagree. The row is written before the workflow starts and closed by
`finalize_campaign` after it ends; if the worker dies in between, is terminated,
or the finalize activity is dropped on a saturated control queue, nothing closes
it. The execution then sits at `running` forever, and with it:

  * the phone stays BUSY until the 1800s campaign claim TTL sweeps it, and on
    a continuous crawl the claim keeps being re-heartbeated, so it may not
    expire at all;
  * `/devices/{serial}/running-workflows` reports a workflow that Temporal has
    never heard of, so the fleet reads busy with nothing to point at;
  * a continuous crawl campaign never leaves `running` — its aggregator is
    disabled while `_continuous_crawl.active` is set, and only the root
    workflow's finalize activity clears that flag.

This worker asks the one authority that can settle the disagreement: does the
workflow still exist? A NOT_FOUND is an answer from the Temporal server, not a
guess — the namespace was reachable and the workflow is not in it. Transport
errors are left alone; an unreachable server must never be read as "the fleet is
idle", because that would tear down runs that are healthy.

Everything here is idempotent and grace-gated: an execution is only considered
after `ORPHAN_REAPER_GRACE_SEC` without finishing, so a workflow that has just
completed and is still finalizing is never raced.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from db.database import AsyncSessionLocal
from db.models.campaign import Campaign
from db.models.enums import CampaignStatus, ExecutionResultStatus, ExecutionStatus
from db.models.execution import Execution, ExecutionResult
from db.models.organization import Organization
from tenancy.context import use_tenant_scope

log = logging.getLogger(__name__)

ORPHAN_REAPER_INTERVAL_SEC = int(
    os.environ.get("EXECUTION_ORPHAN_REAPER_INTERVAL_SEC", "120")
)
ORPHAN_REAPER_GRACE_SEC = int(
    os.environ.get("EXECUTION_ORPHAN_REAPER_GRACE_SEC", "300")
)
ORPHAN_REAPER_BATCH_LIMIT = int(
    os.environ.get("EXECUTION_ORPHAN_REAPER_BATCH_LIMIT", "100")
)
ORPHAN_REAPER_ENABLED = (
    os.environ.get("EXECUTION_ORPHAN_REAPER_ENABLED", "1").strip().lower()
    not in ("0", "false", "no")
)

_ACTIVE_EXECUTION_STATUSES = (
    ExecutionStatus.RUNNING.value,
    ExecutionStatus.PAUSED.value,
)


class WorkflowGone(Exception):
    """The Temporal server answered that this workflow does not exist."""


async def _workflow_is_gone(client, workflow_id: str) -> bool:
    """True only when Temporal positively reports the workflow as absent or done.

    Raises nothing: an unreachable server, a timeout, or any other transport
    fault returns False, which leaves the execution untouched for the next pass.
    """
    from temporalio.service import RPCError, RPCStatusCode

    try:
        desc = await client.get_workflow_handle(workflow_id).describe()
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return True
        log.debug("orphan reaper describe failed id=%s", workflow_id, exc_info=True)
        return False
    except Exception:
        log.debug("orphan reaper describe failed id=%s", workflow_id, exc_info=True)
        return False
    status = desc.status.name if desc.status else "UNKNOWN"
    # RUNNING is healthy. UNKNOWN is not an answer — treat it as "leave alone".
    return status not in ("RUNNING", "UNKNOWN")


def _execution_workflow_id(execution: Execution) -> str:
    from services.campaign.execution_runtime import workflow_id_for_execution

    meta = execution.meta or {}
    return str(meta.get("workflow_id") or workflow_id_for_execution(execution.id))


async def _list_stale_executions(db, *, cutoff: datetime, limit: int) -> list[Execution]:
    """Active executions that have been active longer than the grace period."""
    result = await db.execute(
        select(Execution)
        .where(
            Execution.status.in_(_ACTIVE_EXECUTION_STATUSES),
            Execution.finished_at.is_(None),
            or_(
                Execution.started_at <= cutoff,
                Execution.started_at.is_(None),
            ),
            Execution.created_at <= cutoff,
        )
        .order_by(Execution.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def _list_executions_with_open_results(db, *, limit: int) -> list[tuple[str, str]]:
    """Finished executions that still have a per-device row at pending/running.

    `finish_fan_out_execution` settles these going forward, but any execution
    that reached a terminal state before that existed — or through a path that
    does not go via the dispatcher — left the row open, and cumulative run
    stats keep counting it as a device still in flight.
    """
    result = await db.execute(
        select(Execution.id, Execution.status)
        .join(ExecutionResult, ExecutionResult.execution_id == Execution.id)
        .where(
            Execution.finished_at.is_not(None),
            ExecutionResult.status.in_(
                (
                    ExecutionResultStatus.PENDING.value,
                    ExecutionResultStatus.RUNNING.value,
                )
            ),
        )
        .distinct()
        .limit(limit)
    )
    return [(str(row[0]), str(row[1])) for row in result.all()]


async def _settle_open_results(rows: list[tuple[str, str]]) -> int:
    from db.crud.execution import close_open_execution_results

    closed = 0
    for execution_id, execution_status in rows:
        async with AsyncSessionLocal() as db:
            try:
                closed += await close_open_execution_results(
                    db, execution_id, status=execution_status
                )
                await db.commit()
            except Exception:
                await db.rollback()
                log.warning(
                    "orphan reaper failed to settle result rows execution=%s",
                    execution_id,
                    exc_info=True,
                )
    return closed


async def _reap_one_execution(client, execution_id: str) -> bool:
    """Settle one execution if its workflow is gone. Returns True when settled."""
    from db.crud.execution import get_execution
    from services.campaign.dispatcher import finish_fan_out_execution

    async with AsyncSessionLocal() as db:
        execution = await get_execution(db, execution_id)
        if execution is None or execution.finished_at is not None:
            return False
        if execution.status not in _ACTIVE_EXECUTION_STATUSES:
            return False
        workflow_id = _execution_workflow_id(execution)
        if not await _workflow_is_gone(client, workflow_id):
            return False
        org_id = str(execution.org_id)
        actor_user_id = str(execution.user_id or "system")
        try:
            with use_tenant_scope(org_id):
                await finish_fan_out_execution(
                    db,
                    execution,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                    status=ExecutionStatus.FAILED.value,
                )
            await db.commit()
        except Exception:
            await db.rollback()
            log.warning(
                "orphan reaper failed to settle execution=%s workflow=%s",
                execution_id,
                workflow_id,
                exc_info=True,
            )
            return False
    log.info(
        "orphan reaper settled execution=%s (workflow %s no longer exists)",
        execution_id,
        workflow_id,
    )
    return True


async def _list_org_ids(db) -> list[str]:
    """Every organization, oldest first.

    Campaign is tenant-scoped, so it cannot be swept in one global query — an
    ORM SELECT against it outside a tenant context raises under
    TENANCY_STRICT_MODE, by design. Organization is the tenant itself and is not
    scoped, so it is the one safe place to enumerate from. Executions are swept
    globally because Execution is not tenant-scoped.
    """
    result = await db.execute(select(Organization.id).order_by(Organization.id))
    return [str(row) for row in result.scalars().all()]


async def _list_stale_continuous_crawls(
    db, *, org_id: str, limit: int
) -> list[Campaign]:
    """Active-looking crawl campaigns for one org. Caller supplies tenant scope."""
    result = await db.execute(
        select(Campaign)
        .where(
            Campaign.org_id == org_id,
            Campaign.status.in_(
                (CampaignStatus.RUNNING.value, CampaignStatus.PAUSED.value)
            ),
        )
        .order_by(Campaign.updated_at.asc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return [row for row in rows if _active_crawl_metadata(row) is not None]


def _active_crawl_metadata(campaign: Campaign) -> dict | None:
    metadata = (campaign.variables or {}).get("_continuous_crawl")
    if not isinstance(metadata, dict) or not metadata.get("active", True):
        return None
    if not metadata.get("workflow_id"):
        return None
    return metadata


async def _reap_one_continuous_crawl(client, org_id: str, campaign_id: str) -> bool:
    """Release a continuous crawl campaign whose root workflow is gone.

    Only this flag's owner — the root workflow's finalize activity — normally
    clears it, and the status aggregator stays disabled until it does. A dead
    root would otherwise leave the campaign reading "running" with no pause and
    no way back to a dispatchable state.

    Every Campaign read here runs inside the org's tenant scope; Campaign is
    tenant-scoped and an unscoped ORM SELECT against it is a hard error.
    """
    from services.campaign.lifecycle import transition_campaign_for_org

    async with AsyncSessionLocal() as db:
        with use_tenant_scope(org_id):
            campaign = await db.scalar(
                select(Campaign)
                .where(Campaign.id == campaign_id, Campaign.org_id == org_id)
                .with_for_update()
            )
        if campaign is None:
            return False
        metadata = _active_crawl_metadata(campaign)
        if metadata is None:
            return False
        workflow_id = str(metadata["workflow_id"])
        if not await _workflow_is_gone(client, workflow_id):
            return False
        try:
            with use_tenant_scope(org_id):
                await transition_campaign_for_org(
                    db,
                    org_id=org_id,
                    campaign_id=campaign_id,
                    to_status=CampaignStatus.FAILED.value,
                    user_id=campaign.created_by or campaign.user_id,
                    reason="continuous crawl workflow no longer exists",
                )
            variables = dict(campaign.variables or {})
            variables["_continuous_crawl"] = {
                **metadata,
                "active": False,
                "status": CampaignStatus.FAILED.value,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "reaped": True,
            }
            campaign.variables = variables
            await db.commit()
        except Exception:
            await db.rollback()
            log.warning(
                "orphan reaper failed to release crawl campaign=%s workflow=%s",
                campaign_id,
                workflow_id,
                exc_info=True,
            )
            return False
    log.info(
        "orphan reaper released continuous crawl campaign=%s "
        "(workflow %s no longer exists)",
        campaign_id,
        workflow_id,
    )
    return True


async def reap_orphans_once(temporal_config) -> tuple[int, int]:
    """One pass. Returns (executions settled, crawl campaigns released)."""
    from db.database import schema_init_ok

    if not ORPHAN_REAPER_ENABLED or schema_init_ok is not True:
        return (0, 0)
    if temporal_config is None or not getattr(temporal_config, "enabled", False):
        return (0, 0)

    from temporal.worker import get_temporal_client

    client = await get_temporal_client(temporal_config)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ORPHAN_REAPER_GRACE_SEC)

    async with AsyncSessionLocal() as db:
        stale_executions = await _list_stale_executions(
            db, cutoff=cutoff, limit=ORPHAN_REAPER_BATCH_LIMIT
        )
        execution_ids = [str(row.id) for row in stale_executions]
        crawl_candidates: list[tuple[str, str]] = []
        for org_id in await _list_org_ids(db):
            with use_tenant_scope(org_id):
                rows = await _list_stale_continuous_crawls(
                    db, org_id=org_id, limit=ORPHAN_REAPER_BATCH_LIMIT
                )
            crawl_candidates.extend((org_id, str(row.id)) for row in rows)
        open_result_rows = await _list_executions_with_open_results(
            db, limit=ORPHAN_REAPER_BATCH_LIMIT
        )

    closed_results = await _settle_open_results(open_result_rows)
    if closed_results:
        log.info("orphan reaper closed %s stale result row(s)", closed_results)

    settled = 0
    for execution_id in execution_ids:
        if await _reap_one_execution(client, execution_id):
            settled += 1

    # Campaigns after executions: settling the last execution of a crawl lets
    # the aggregator finish the campaign on its own, and then this is a no-op.
    released = 0
    for org_id, campaign_id in crawl_candidates:
        if await _reap_one_continuous_crawl(client, org_id, campaign_id):
            released += 1

    return (settled, released)


async def reap_orphans_loop(temporal_config) -> None:
    if not ORPHAN_REAPER_ENABLED:
        log.info("execution orphan reaper disabled by configuration")
        return
    if temporal_config is None or not getattr(temporal_config, "enabled", False):
        log.info("execution orphan reaper idle: Temporal is not enabled")
        return
    log.info(
        "execution orphan reaper started (interval=%ss grace=%ss batch=%s)",
        ORPHAN_REAPER_INTERVAL_SEC,
        ORPHAN_REAPER_GRACE_SEC,
        ORPHAN_REAPER_BATCH_LIMIT,
    )
    while True:
        try:
            settled, released = await reap_orphans_once(temporal_config)
            if settled or released:
                log.info(
                    "execution orphan reaper settled %s execution(s), "
                    "released %s crawl campaign(s)",
                    settled,
                    released,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("execution orphan reaper iteration failed")
        await asyncio.sleep(ORPHAN_REAPER_INTERVAL_SEC)
