"""DLQ orchestrator — open, replay, close (DF-T-04-012)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.execution import (
    add_device_to_execution,
    create_execution,
    get_execution,
    update_execution,
    upsert_execution_result,
)
from db.crud.execution_dlq import (
    begin_dlq_retry_for_user,
    close_dlq_entry_for_user,
    create_dlq_entry,
    get_dlq_by_execution_for_user,
    get_dlq_entry_for_user,
    mark_dlq_replayed,
    set_dlq_status,
)
from db.models.enums import DLQStatus, ExecutionStatus
from db.models.execution_dlq import ExecutionDLQ
from services.campaign.dlq_errors import (
    DLQAlreadyClosedError,
    DLQError,
    DLQNotFoundError,
    DLQRetryInProgressError,
)
from services.campaign.dlq_events import emit_dlq_domain_event
from services.campaign.dispatcher import (
    CampaignDispatcher,
    FanOutExecutionView,
    FanOutResult,
)

log = logging.getLogger(__name__)

from services.campaign.execution_runtime import (  # noqa: E402
    DISPATCH_SOURCE_FALLBACK,
    DISPATCH_SOURCE_TEMPORAL,
)

_CLOSED_DLQ = frozenset({
    DLQStatus.CLOSED.value,
    DLQStatus.DISMISSED.value,
    DLQStatus.REPLAYED.value,
    DLQStatus.RESOLVED.value,
})


from services.campaign.dlq_message import (
    coalesce_dlq_text,
    failure_from_step_results,
    last_failed_step_for_execution,
    pick_richer_message,
)


def uses_epic04_replay(execution: Any) -> bool:
    """True when replay should use per-execution runtime (DF-T-04-010) instead of legacy enqueue."""
    meta = dict(getattr(execution, "meta", None) or {})
    if meta.get("dispatch_source") in (DISPATCH_SOURCE_TEMPORAL, DISPATCH_SOURCE_FALLBACK):
        return True
    if meta.get("org_scenario_refs"):
        return True
    return bool(meta.get("dlq_replay"))


def _artifact_refs_from_steps(step_results: list[dict[str, Any]]) -> dict[str, Any]:
    from services.execution.step_store import extract_artifacts_json, normalize_workflow_step_result

    failed = [s for s in step_results if not s.get("ok", True)]
    if not failed:
        return {}
    last = normalize_workflow_step_result(failed[-1])
    refs: dict[str, Any] = {}
    for key in ("screenshot_post", "screenshot_pre", "url"):
        val = last.get(key)
        if val:
            refs[key] = val
    screenshot = last.get("screenshot")
    if isinstance(screenshot, dict):
        if screenshot.get("full"):
            refs["screenshot_post"] = refs.get("screenshot_post") or screenshot.get("full")
        if screenshot.get("hierarchy"):
            refs["hierarchy_url"] = screenshot.get("hierarchy")
    elif isinstance(screenshot, str):
        refs["screenshot_post"] = refs.get("screenshot_post") or screenshot
    pre = last.get("screenshot_pre")
    if isinstance(pre, dict) and pre.get("full"):
        refs["screenshot_pre"] = refs.get("screenshot_pre") or pre.get("full")
    for art in extract_artifacts_json(failed[-1]):
        art_type = str(art.get("type") or "")
        if art_type == "fail" and art.get("screenshot_url"):
            refs["screenshot_fail"] = art.get("screenshot_url")
            refs["screenshot_post"] = refs.get("screenshot_post") or art.get("screenshot_url")
        if art.get("hierarchy_url"):
            refs["hierarchy_url"] = art.get("hierarchy_url")
    return refs


async def open_dlq_for_failed_execution(
    db: AsyncSession,
    *,
    execution_id: str,
    device_serial: str,
    step_results: list[dict[str, Any]] | None = None,
    error_msg: str | None = None,
    org_id: str = "",
    user_id: str | None = None,
) -> ExecutionDLQ:
    """Create/open DLQ entry and mark execution dlq_open (Epic 04 path)."""
    execution = await get_execution(db, execution_id)
    step_results = step_results or []
    failed_step_id, failure_reason = failure_from_step_results(step_results, error_msg)
    if not failure_reason:
        step_msg, step_id_from_row = await last_failed_step_for_execution(db, execution_id)
        failure_reason = step_msg
        failed_step_id = failed_step_id or step_id_from_row
    resolved_error = coalesce_dlq_text(error_msg, failure_reason)
    resolved_reason = pick_richer_message(failure_reason, resolved_error) or resolved_error
    artifact_refs = _artifact_refs_from_steps(step_results)
    now = datetime.now(timezone.utc)
    execution_org_id = str(getattr(execution, "org_id", None) or "").strip()
    supplied_org_id = str(org_id or "").strip()
    if supplied_org_id and execution_org_id and supplied_org_id != execution_org_id:
        raise ValueError(
            f"DLQ org_id mismatch for execution {execution_id}: "
            f"expected {execution_org_id}, got {supplied_org_id}"
        )
    resolved_org_id = execution_org_id

    entry = await create_dlq_entry(
        db,
        execution_id=execution_id,
        device_serial=device_serial,
        org_id=resolved_org_id,
        error=resolved_error,
        failed_step_id=failed_step_id,
        failure_reason=resolved_reason,
        failed_at=now,
        campaign_id=execution.campaign_id if execution else None,
        artifact_refs=artifact_refs,
    )

    if execution and execution.status not in (
        ExecutionStatus.CANCELLED.value,
        ExecutionStatus.DLQ_CLOSED.value,
    ):
        await update_execution(db, execution_id, status=ExecutionStatus.DLQ_OPEN.value)

    if resolved_org_id:
        await emit_dlq_domain_event(
            db,
            event="execution.dlq.opened",
            org_id=resolved_org_id,
            execution_id=execution_id,
            user_id=user_id,
            details={
                "dlq_id": entry.id,
                "device_serial": device_serial,
                "failed_step_id": failed_step_id,
                "failure_reason": failure_reason,
                "artifact_refs": artifact_refs,
            },
        )
        from services.execution.event_publisher import enqueue_execution_event
        from services.execution.event_types import EXECUTION_DLQ_OPENED

        await enqueue_execution_event(
            db,
            event_type=EXECUTION_DLQ_OPENED,
            execution_id=execution_id,
            organization_id=resolved_org_id,
            campaign_id=execution.campaign_id if execution else None,
            step_id=failed_step_id,
            payload={
                "dlq_id": entry.id,
                "device_serial": device_serial,
                "failure_reason": failure_reason,
                "artifact_refs": artifact_refs,
            },
        )
    return entry


async def get_dlq_detail_for_user(
    db: AsyncSession,
    *,
    execution_id: str,
    user_id: str | None,
    org_id: str | None,
) -> ExecutionDLQ:
    entry = await get_dlq_by_execution_for_user(
        db, execution_id, user_id, org_id=org_id,
    )
    if entry is None:
        raise DLQNotFoundError()
    return entry


def _assert_replay_allowed(entry: ExecutionDLQ, *, changed: bool) -> None:
    if entry.status in _CLOSED_DLQ:
        raise DLQAlreadyClosedError()
    if entry.status == DLQStatus.RETRYING.value and not changed:
        raise DLQRetryInProgressError()


async def _create_replay_execution(
    db: AsyncSession,
    *,
    source: Any,
    entry: ExecutionDLQ,
    campaign: Any,
    device_id: str,
    device_serial: str,
    from_checkpoint: bool,
) -> Any:
    checkpoint = int(source.checkpoint_step or 0) if from_checkpoint else 0
    source_meta = dict(source.meta or {})
    source_cfg = dict(source.device_config or {})
    dispatch_id = f"dlq-replay-{entry.id[:8]}-{uuid.uuid4().hex[:6]}"
    scenario_refs = source_meta.get("org_scenario_refs")
    if not isinstance(scenario_refs, list) or not scenario_refs:
        from services.campaign.scenario_sources import resolve_campaign_scenario_refs

        scenario_refs = await resolve_campaign_scenario_refs(db, campaign)

    replay_meta = {
        k: v
        for k, v in source_meta.items()
        if k not in ("workflow_id", "workflow_ids", "dispatch_source")
    }
    replay_meta.update(
        {
            "replayed_from": source.id,
            "dlq_replay": True,
            "dlq_id": entry.id,
            "dispatch_id": dispatch_id,
            "org_scenario_refs": scenario_refs,
            "start_step": checkpoint,
            "queued": True,
        }
    )

    new_execution = await create_execution(
        db,
        run_type=source.run_type or "campaign_device",
        campaign_id=source.campaign_id,
        user_id=source.user_id,
        account_id=source.account_id,
        status=ExecutionStatus.PENDING.value,
        meta=replay_meta,
        device_config={
            **source_cfg,
            "device_serial": device_serial,
            "effective_vars": dict(source_cfg.get("effective_vars") or {}),
            "account_vars": dict(source_cfg.get("account_vars") or {}),
        },
    )
    new_execution.checkpoint_step = checkpoint
    await add_device_to_execution(db, new_execution.id, device_id)
    await upsert_execution_result(
        db,
        execution_id=new_execution.id,
        device_id=device_id,
        status="pending",
    )
    await db.flush()
    return new_execution


async def replay_dlq_entry(
    db: AsyncSession,
    *,
    dlq_id: str,
    user_id: str | None,
    org_id: str | None,
    actor_user_id: str,
    from_checkpoint: bool = True,
    temporal_client: Any = None,
    temporal_config: Any = None,
    manager: Any = None,
) -> tuple[ExecutionDLQ, Any, bool]:
    """Replay a DLQ entry into a new execution. Returns (entry, new_execution|None, changed)."""
    entry, changed = await begin_dlq_retry_for_user(
        db, dlq_id, user_id, org_id=org_id,
    )
    if entry is None:
        raise DLQNotFoundError()
    _assert_replay_allowed(entry, changed=changed)
    if not changed:
        raise DLQRetryInProgressError()

    source = await get_execution(db, entry.execution_id)
    if source is None or not source.campaign_id:
        await set_dlq_status(
            db, dlq_id, DLQStatus.PENDING.value,
            error="DLQ replay only supports campaign-linked executions",
        )
        raise DLQError(
            "Execution is not linked to a campaign",
            code="DLQ_REPLAY_UNSUPPORTED",
            http_status=400,
        )

    from db.crud import campaign_entity as campaign_repo
    from db.crud.device import get_device_by_serial

    campaign = await campaign_repo.get_campaign_entity(db, source.campaign_id)
    if campaign is None or (org_id and campaign.org_id != org_id):
        raise DLQNotFoundError("Campaign not found for DLQ replay")

    device = await get_device_by_serial(db, entry.device_serial)
    if device is None:
        await set_dlq_status(db, dlq_id, DLQStatus.PENDING.value, error="Device not found")
        raise DLQError("Device not found", code="DEVICE_NOT_FOUND", http_status=404)

    new_execution = await _create_replay_execution(
        db,
        source=source,
        entry=entry,
        campaign=campaign,
        device_id=device.id,
        device_serial=device.serial,
        from_checkpoint=from_checkpoint,
    )

    dispatcher = CampaignDispatcher()
    view = await dispatcher.activate_queued_execution(
        db,
        execution=new_execution,
        campaign=campaign,
        org_id=org_id or campaign.org_id,
        actor_user_id=actor_user_id,
    )
    if view is None or view.status != ExecutionStatus.RUNNING.value:
        await set_dlq_status(
            db,
            dlq_id,
            DLQStatus.PENDING.value,
            error=view.failure_reason if view else "device_claim_failed",
        )
        raise DLQError(
            view.failure_reason if view else "Failed to activate replay execution",
            code="DEVICE_CLAIM_FAILED",
            http_status=409,
        )

    fan_out = FanOutResult(
        dispatch_id=new_execution.meta.get("dispatch_id", f"dlq-{entry.id}"),
        campaign_id=campaign.id,
        dispatch_strategy="parallel",
        executions=[view],
    )

    from services.campaign.execution_runtime import start_execution_runtime

    await start_execution_runtime(
        db,
        fan_out=fan_out,
        campaign=campaign,
        org_id=org_id or campaign.org_id,
        actor_user_id=actor_user_id,
        temporal_client=temporal_client,
        temporal_config=temporal_config,
        manager=manager,
    )

    entry = await mark_dlq_replayed(
        db, dlq_id, replayed_to_execution_id=new_execution.id,
    ) or entry

    await emit_dlq_domain_event(
        db,
        event="execution.dlq.replayed",
        org_id=org_id or campaign.org_id,
        execution_id=source.id,
        user_id=actor_user_id,
        details={
            "dlq_id": entry.id,
            "replayed_to_execution_id": new_execution.id,
            "from_checkpoint": from_checkpoint,
            "start_step": new_execution.checkpoint_step,
        },
    )
    from services.execution.event_publisher import enqueue_execution_event
    from services.execution.event_types import EXECUTION_DLQ_REPLAYED

    await enqueue_execution_event(
        db,
        event_type=EXECUTION_DLQ_REPLAYED,
        execution_id=source.id,
        organization_id=org_id or campaign.org_id,
        campaign_id=campaign.id,
        payload={
            "dlq_id": entry.id,
            "replayed_to_execution_id": new_execution.id,
            "from_checkpoint": from_checkpoint,
        },
    )
    return entry, new_execution, True


async def close_dlq_entry(
    db: AsyncSession,
    *,
    dlq_id: str,
    user_id: str | None,
    org_id: str | None,
    closed_by: str,
    close_reason: str,
) -> ExecutionDLQ:
    entry = await get_dlq_entry_for_user(db, dlq_id, user_id, org_id=org_id)
    if entry is None:
        raise DLQNotFoundError()
    if entry.status in _CLOSED_DLQ:
        raise DLQAlreadyClosedError()

    entry = await close_dlq_entry_for_user(
        db,
        dlq_id,
        user_id=user_id,
        org_id=org_id,
        closed_by=closed_by,
        close_reason=close_reason,
    )
    assert entry is not None

    execution = await get_execution(db, entry.execution_id)
    if execution and execution.status == ExecutionStatus.DLQ_OPEN.value:
        await update_execution(db, execution.id, status=ExecutionStatus.DLQ_CLOSED.value)

    resolved_org = org_id or ""
    if execution and not resolved_org:
        from services.execution.event_publisher import resolve_execution_org_id

        resolved_org = await resolve_execution_org_id(db, execution)

    if resolved_org:
        await emit_dlq_domain_event(
            db,
            event="execution.dlq.closed",
            org_id=resolved_org,
            execution_id=entry.execution_id,
            user_id=closed_by,
            details={
                "dlq_id": entry.id,
                "close_reason": close_reason,
            },
        )
        from services.execution.event_publisher import enqueue_execution_event
        from services.execution.event_types import EXECUTION_DLQ_CLOSED

        await enqueue_execution_event(
            db,
            event_type=EXECUTION_DLQ_CLOSED,
            execution_id=entry.execution_id,
            organization_id=resolved_org,
            campaign_id=execution.campaign_id if execution else None,
            payload={"dlq_id": entry.id, "close_reason": close_reason},
        )
        if execution and execution.campaign_id:
            from services.campaign.aggregator_scheduler import request_campaign_status_evaluation

            await request_campaign_status_evaluation(
                org_id=resolved_org,
                campaign_id=execution.campaign_id,
                user_id=closed_by,
            )
    return entry


async def legacy_retry_dlq_entry(
    db: AsyncSession,
    *,
    dlq_id: str,
    user_id: str | None,
    org_id: str | None,
    temporal_client: Any,
    temporal_config: Any,
    manager: Any = None,
    offline_after_minutes: int = 5,
) -> ExecutionDLQ:
    """Legacy campaign re-enqueue path (pre–Epic 04 fan-out runtime)."""
    from db import crud as repo
    from db.crud.device import get_device_by_serial
    from db.crud.execution_dlq import mark_dlq_resolved, set_dlq_status
    from services.campaign_dispatch import enqueue_campaign_run_temporal
    from services.device_liveness import is_device_dispatchable

    entry, changed = await begin_dlq_retry_for_user(
        db, dlq_id, user_id, org_id=org_id,
    )
    if entry is None:
        raise DLQNotFoundError()
    _assert_replay_allowed(entry, changed=changed)
    if not changed:
        raise DLQRetryInProgressError()

    source = await get_execution(db, entry.execution_id)
    if source is None or not source.campaign_id:
        await set_dlq_status(
            db,
            dlq_id,
            DLQStatus.PENDING.value,
            error="DLQ retry only supports campaign-linked executions",
        )
        raise DLQError(
            "Execution is not linked to a campaign",
            code="DLQ_REPLAY_UNSUPPORTED",
            http_status=400,
        )

    if temporal_client is None:
        await set_dlq_status(
            db,
            dlq_id,
            DLQStatus.PENDING.value,
            error="Temporal client unavailable for retry",
        )
        raise DLQError(
            "Temporal is unavailable",
            code="TEMPORAL_UNAVAILABLE",
            http_status=503,
        )

    user_org = org_id or (await repo.get_user_org_id(db, user_id) if user_id else None)
    device = await get_device_by_serial(db, entry.device_serial)
    if device is None or (user_org and device.org_id != user_org):
        await set_dlq_status(
            db,
            dlq_id,
            DLQStatus.DISMISSED.value,
            error="Device is not available for retry",
        )
        return entry

    device_live = await is_device_dispatchable(
        db,
        device,
        offline_after_minutes=offline_after_minutes,
        manager=manager,
    )
    if not device_live:
        await set_dlq_status(
            db,
            dlq_id,
            DLQStatus.DISMISSED.value,
            error="Device is offline; DLQ retry skipped",
        )
        return entry

    payload, status_code = await enqueue_campaign_run_temporal(
        source.campaign_id,
        temporal_client,
        temporal_config,
        device_serials_override=[entry.device_serial],
    )
    if status_code >= 400:
        error_msg = payload.get("error", "retry enqueue failed")
        await set_dlq_status(db, dlq_id, DLQStatus.PENDING.value, error=error_msg)
        raise DLQError(error_msg, code="DLQ_RETRY_ENQUEUE_FAILED", http_status=status_code)

    entry = await mark_dlq_resolved(db, dlq_id) or entry
    return entry


async def bulk_replay_dlq(
    db: AsyncSession,
    *,
    dlq_ids: list[str] | None = None,
    execution_ids: list[str] | None = None,
    user_id: str | None,
    org_id: str | None,
    actor_user_id: str,
    from_checkpoint: bool = True,
    temporal_client: Any = None,
    temporal_config: Any = None,
    manager: Any = None,
    offline_after_minutes: int = 5,
    max_items: int = 50,
) -> list[dict[str, Any]]:
    resolved_ids: list[str] = list(dlq_ids or [])
    if execution_ids:
        for execution_id in execution_ids:
            entry = await get_dlq_by_execution_for_user(
                db, execution_id, user_id, org_id=org_id,
            )
            if entry is not None:
                resolved_ids.append(entry.id)
            else:
                resolved_ids.append(f"__missing__:{execution_id}")

    results: list[dict[str, Any]] = []
    for dlq_id in resolved_ids[:max_items]:
        if dlq_id.startswith("__missing__:"):
            results.append(
                {
                    "execution_id": dlq_id.split(":", 1)[1],
                    "status": "error",
                    "reason": "DLQ_NOT_FOUND",
                }
            )
            continue
        try:
            entry_row = await get_dlq_entry_for_user(db, dlq_id, user_id, org_id=org_id)
            if entry_row is None:
                results.append({"dlq_id": dlq_id, "status": "error", "reason": "DLQ_NOT_FOUND"})
                continue
            source = await get_execution(db, entry_row.execution_id)
            if source and uses_epic04_replay(source):
                entry, new_ex, _ = await replay_dlq_entry(
                    db,
                    dlq_id=dlq_id,
                    user_id=user_id,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                    from_checkpoint=from_checkpoint,
                    temporal_client=temporal_client,
                    temporal_config=temporal_config,
                    manager=manager,
                )
                results.append(
                    {
                        "dlq_id": dlq_id,
                        "execution_id": entry_row.execution_id,
                        "status": "replayed",
                        "replayed_to_execution_id": new_ex.id,
                        "entry_status": entry.status,
                    }
                )
            else:
                entry = await legacy_retry_dlq_entry(
                    db,
                    dlq_id=dlq_id,
                    user_id=user_id,
                    org_id=org_id,
                    temporal_client=temporal_client,
                    temporal_config=temporal_config,
                    manager=manager,
                    offline_after_minutes=offline_after_minutes,
                )
                results.append(
                    {
                        "dlq_id": dlq_id,
                        "execution_id": entry_row.execution_id,
                        "status": "resolved" if entry.status == DLQStatus.RESOLVED.value else entry.status,
                        "entry_status": entry.status,
                    }
                )
        except DLQAlreadyClosedError as exc:
            results.append(
                {
                    "dlq_id": dlq_id,
                    "status": "skipped",
                    "reason": exc.code,
                }
            )
        except DLQError as exc:
            results.append(
                {
                    "dlq_id": dlq_id,
                    "status": "error",
                    "reason": exc.code,
                    "message": str(exc),
                }
            )
        except DLQNotFoundError:
            results.append({"dlq_id": dlq_id, "status": "error", "reason": "DLQ_NOT_FOUND"})
    return results
