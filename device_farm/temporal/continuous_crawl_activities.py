"""Database-backed Temporal activities for continuous crawls."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from temporalio import activity

from db.database import activity_session
from db.models.campaign import Campaign
from db.models.device import Device
from db.models.execution import Execution, ExecutionDevice, ExecutionResult
from db.models.external_entity import ExecutionEntityAssignment, ExternalEntity
from services.campaign.continuous_crawl import crawl_execution_idempotency_key
from services.campaign.entity_allocation import (
    SourcePoolSpec,
    load_assigned_target_page,
)
from temporal.continuous_crawl_workflows import (
    CleanupCrawlTargetInput,
    CrawlTarget,
    FinalizeCrawlInput,
    LoadCrawlPageInput,
    LoadCrawlPageResult,
    PrepareCrawlTargetInput,
    PreparedCrawlTarget,
)
from tenancy.context import use_tenant_scope


def _source_pool_spec(raw: dict[str, Any]) -> SourcePoolSpec:
    statuses = raw.get("statuses")
    return SourcePoolSpec(
        platform=str(raw.get("platform") or ""),
        entity_type=str(raw.get("entity_type") or ""),
        search=str(raw["search"]) if raw.get("search") else None,
        statuses=tuple(map(str, statuses))
        if statuses
        else ("candidate", "active", "available"),
        output_prefix=str(raw["output_prefix"]) if raw.get("output_prefix") else None,
    )


def _snapshot(entity: ExternalEntity) -> dict[str, Any]:
    attributes = entity.current_attributes or {}
    locator = attributes.get("locator") if isinstance(attributes, dict) else None
    return {
        "id": entity.id,
        "platform": entity.platform,
        "entity_type": entity.entity_type,
        "external_id": entity.external_id,
        "canonical_url": entity.canonical_url,
        "display_name": entity.display_name,
        "attributes": {"locator": dict(locator)} if isinstance(locator, dict) else {},
    }


def _entity_vars(value: dict[str, Any], prefix_raw: str | None) -> dict[str, Any]:
    values = {
        "TARGET_ENTITY_ID": value["id"],
        "TARGET_PLATFORM": value["platform"],
        "TARGET_ENTITY_TYPE": value["entity_type"],
        "TARGET_EXTERNAL_ID": value.get("external_id") or "",
        "TARGET_URL": value.get("canonical_url") or "",
        "TARGET_NAME": value["display_name"],
    }
    prefix = "".join(
        c if c.isascii() and (c.isalnum() or c == "_") else "_"
        for c in str(prefix_raw or "").strip().upper()
    ).strip("_")[:32]
    if prefix:
        values.update({k.replace("TARGET", prefix, 1): v for k, v in values.items()})
    attributes = value.get("attributes") or {}
    locator = (
        attributes.get("locator")
        if isinstance(attributes, dict) and isinstance(attributes.get("locator"), dict)
        else {}
    )
    selector = (
        locator.get("selector") if isinstance(locator.get("selector"), dict) else {}
    )
    fallback_selector = (
        locator.get("fallback_selector")
        if isinstance(locator.get("fallback_selector"), dict)
        else {}
    )
    name = str(value["display_name"])
    is_facebook_group = (
        value["platform"] == "facebook" and value["entity_type"] == "group"
    )
    default_selector_by = "descriptionStartsWith" if is_facebook_group else "text"
    default_selector_value = f"{name}," if is_facebook_group else name
    default_fallback_by = "descriptionContains" if is_facebook_group else "textContains"
    locator_vars = {
        "SEARCH_QUERY": str(locator.get("search_query") or name),
        "SELECTOR_BY": str(selector.get("by") or default_selector_by),
        "SELECTOR_VALUE": str(selector.get("value") or default_selector_value),
        "FALLBACK_SELECTOR_BY": str(fallback_selector.get("by") or default_fallback_by),
        "FALLBACK_SELECTOR_VALUE": str(fallback_selector.get("value") or name),
    }
    values.update({f"TARGET_{key}": item for key, item in locator_vars.items()})
    values["TARGET_LOCATOR"] = locator
    if prefix:
        values.update({f"{prefix}_{key}": item for key, item in locator_vars.items()})
    if is_facebook_group:
        values.update({"GROUP_NAME": name, "TARGET_GROUP_NAME": name})
    return values


@activity.defn
async def load_continuous_crawl_source_page(
    inp: LoadCrawlPageInput,
) -> LoadCrawlPageResult:
    snapshot_at = datetime.fromisoformat(inp.snapshot_at)
    if snapshot_at.tzinfo is None:
        snapshot_at = snapshot_at.replace(tzinfo=UTC)
    async with activity_session() as db:
        page = await load_assigned_target_page(
            db,
            org_id=inp.org_id,
            spec=_source_pool_spec(inp.source_pool),
            dispatch_id=inp.dispatch_id,
            device_serials=inp.device_serials,
            snapshot_at=snapshot_at,
            cursor=inp.cursor,
            limit=inp.limit,
        )
        return LoadCrawlPageResult(
            [
                CrawlTarget(
                    str(item.entity.id),
                    _snapshot(item.entity),
                    device_serial=item.device_serial,
                )
                for item in page.items
            ],
            page.next_cursor,
            page.exhausted,
        )


@activity.defn
async def prepare_continuous_crawl_target(
    inp: PrepareCrawlTargetInput,
) -> PreparedCrawlTarget:
    from db.models.enums import DeviceReserveOwnerType
    from services.campaign.account_resolver import resolve_accounts_for_devices
    from services.campaign.execution_runtime import (
        _scenario_refs_with_recovery_refs,
        prepare_scenario_input,
    )
    from services.campaign.override_resolver import merge_effective_vars
    from services.campaign.scenario_sources import (
        build_campaign_scenario_registry,
        resolve_campaign_scenario_refs,
    )
    from services.device_reserve.service import claim_device_session

    key = crawl_execution_idempotency_key(
        inp.campaign_id,
        inp.dispatch_id,
        inp.device_serial,
        inp.target.external_entity_id,
    )
    async with activity_session() as db:
        with use_tenant_scope(inp.org_id):
            campaign = await db.scalar(
                select(Campaign)
                .where(Campaign.id == inp.campaign_id, Campaign.org_id == inp.org_id)
                .options(selectinload(Campaign.org_scenario_refs))
            )
        device = await db.scalar(
            select(Device).where(
                Device.org_id == inp.org_id, Device.serial == inp.device_serial
            )
        )
        if not campaign or not device:
            raise ValueError("continuous crawl campaign or device not found")
        scenario_refs = await resolve_campaign_scenario_refs(db, campaign)
        if not scenario_refs:
            raise ValueError("continuous crawl campaign has no scenarios")
        registry_refs = _scenario_refs_with_recovery_refs(
            scenario_refs,
            dict(getattr(campaign, "recovery_policy", None) or {}),
        )
        scenario_registry = await build_campaign_scenario_registry(
            db,
            campaign=campaign,
            org_id=inp.org_id,
            scenario_refs=registry_refs,
        )
        from services.platform_session_runtime import (
            guard_reason_allows_login_recovery,
            scenario_registry_has_platform_login_gate,
        )

        allows_facebook_login_recovery = scenario_registry_has_platform_login_gate(
            scenario_registry,
            scenario_refs,
        )

        execution = await db.scalar(
            select(Execution).where(
                Execution.org_id == inp.org_id,
                Execution.idempotency_key == key,
            )
        )
        if execution is None:
            now = datetime.now(UTC)
            execution = Execution(
                run_type="campaign_run",
                kind="campaign",
                status="running",
                org_id=inp.org_id,
                campaign_id=campaign.id,
                user_id=campaign.user_id,
                idempotency_key=key,
                started_at=now,
                meta={
                    "dispatch_id": inp.dispatch_id,
                    "external_entity_id": inp.target.external_entity_id,
                    "dispatch_source": "continuous_crawl",
                },
            )
            db.add(execution)
            await db.flush()
            account = (
                await resolve_accounts_for_devices(
                    db, campaign=campaign, org_id=inp.org_id, device_ids=[device.id]
                )
            )[device.id]
            if account.unavailable:
                raise ValueError(
                    account.failure_reason or "campaign account unavailable"
                )
            from services.facebook_session_guard import guard_facebook_session

            guard = await guard_facebook_session(
                db,
                org_id=inp.org_id,
                device_id=device.id,
                account_id=account.account_id,
                device_serial=device.serial,
                live_check=False,
            )
            session_guard_deferred = (
                allows_facebook_login_recovery
                and guard.blocks_execution
                and guard_reason_allows_login_recovery(guard.reason)
            )
            execution.meta = {
                **(execution.meta or {}),
                "facebook_session_guard": {
                    **guard.to_meta(),
                    **(
                        {"deferred_to_scenario_login": True}
                        if session_guard_deferred
                        else {}
                    ),
                },
            }
            if guard.blocks_execution and not session_guard_deferred:
                raise ValueError(guard.reason)
            effective_vars = merge_effective_vars(
                campaign_vars=campaign.variables,
                per_device_overrides=campaign.per_device_overrides,
                device_id=device.id,
            )
            effective_vars.update(
                _entity_vars(
                    dict(inp.target.payload),
                    _source_pool_spec(inp.source_pool).output_prefix,
                )
            )
            actor_user_id = str(campaign.created_by or campaign.user_id or "system")
            claim = await claim_device_session(
                db,
                device_id=device.id,
                org_id=inp.org_id,
                actor_user_id=actor_user_id,
                owner_type=DeviceReserveOwnerType.CAMPAIGN.value,
                owner_id=campaign.id,
                ctx={"dispatch_id": inp.dispatch_id, "execution_id": execution.id},
            )
            execution.account_id = account.account_id
            execution.device_config = {
                "claim_session_id": claim.session_id,
                "device_serial": device.serial,
                "effective_vars": effective_vars,
                "account_vars": dict(account.account_vars),
            }
            db.add_all(
                [
                    ExecutionDevice(execution_id=execution.id, device_id=device.id),
                    ExecutionResult(
                        org_id=inp.org_id,
                        execution_id=execution.id,
                        device_id=device.id,
                        status="running",
                        started_at=now,
                    ),
                    ExecutionEntityAssignment(
                        org_id=inp.org_id,
                        dispatch_id=inp.dispatch_id,
                        execution_id=execution.id,
                        device_id=device.id,
                        external_entity_id=inp.target.external_entity_id,
                        assignment_key="primary",
                        snapshot=dict(inp.target.payload),
                    ),
                ]
            )

        config = dict(execution.device_config or {})
        if not config.get("effective_vars"):
            raise ValueError("continuous crawl execution is missing prepared variables")
        scenario = await prepare_scenario_input(
            db,
            execution=execution,
            campaign=campaign,
            org_id=inp.org_id,
            device_serial=str(config.get("device_serial") or device.serial),
            effective_vars=dict(config["effective_vars"]),
            account_vars=dict(config.get("account_vars") or {}),
            scenario_refs=scenario_refs,
            scenario_registry=scenario_registry,
            device_id=device.id,
        )
        if scenario is None:
            raise ValueError("continuous crawl campaign has no executable scenarios")
        await db.commit()
        return PreparedCrawlTarget(scenario)


@activity.defn
async def cleanup_continuous_crawl_target(inp: CleanupCrawlTargetInput) -> None:
    from services.campaign.dispatcher import finish_fan_out_execution

    key = crawl_execution_idempotency_key(
        inp.campaign_id,
        inp.dispatch_id,
        inp.device_serial,
        inp.external_entity_id,
    )
    async with activity_session() as db:
        execution = await db.scalar(
            select(Execution).where(
                Execution.org_id == inp.org_id,
                Execution.idempotency_key == key,
            )
        )
        if execution is None or execution.finished_at is not None:
            return
        device = await db.scalar(
            select(Device).where(
                Device.org_id == inp.org_id,
                Device.serial == inp.device_serial,
            )
        )
        await finish_fan_out_execution(
            db,
            execution,
            org_id=inp.org_id,
            actor_user_id=str(execution.user_id or "system"),
            status="failed",
            device_id=device.id if device else None,
        )


@activity.defn
async def finalize_continuous_crawl(inp: FinalizeCrawlInput) -> None:
    from services.campaign.lifecycle import transition_campaign_for_org

    async with activity_session() as db:
        with use_tenant_scope(inp.org_id):
            campaign = await db.scalar(
                select(Campaign)
                .where(Campaign.id == inp.campaign_id, Campaign.org_id == inp.org_id)
                .with_for_update()
            )
        if campaign is None:
            return
        variables = dict(campaign.variables or {})
        metadata = variables.get("_continuous_crawl")
        if (
            not isinstance(metadata, dict)
            or metadata.get("dispatch_id") != inp.dispatch_id
        ):
            return
        now = datetime.now(UTC)
        await transition_campaign_for_org(
            db,
            org_id=inp.org_id,
            campaign_id=inp.campaign_id,
            to_status=inp.status,
            user_id=campaign.created_by or campaign.user_id,
            reason=inp.progress.message or "continuous crawl finalized",
        )
        variables["_continuous_crawl"] = {
            **metadata,
            "active": False,
            "status": inp.status,
            "finished_at": now.isoformat(),
            "progress": dict(inp.progress.__dict__),
        }
        campaign.variables = variables
        await db.commit()
