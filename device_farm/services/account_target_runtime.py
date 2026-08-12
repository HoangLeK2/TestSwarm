"""Durable account-scoped leasing for content and other external targets."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, literal_column, or_, select

from db.models.account_action import AccountAction
from db.models.content import ContentItem
from db.models.execution import Execution, ExecutionDevice
from db.models.external_entity import DeviceTargetGroup, ExternalEntity
from services.account_actions.contract import AccountActionStatus
from services.account_actions.coordinator import _resolve_tenant
from services.account_actions.service import create_action, stable_account_target_key
from tenancy.context import tenant_context


def _keywords(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        parts: Iterable[Any] = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = ()
    return tuple(
        dict.fromkeys(
            clean
            for item in parts
            if (clean := str(item or "").strip())
        )
    )


def _keyword_filter(db: Any, search_terms: tuple[str, ...]) -> Any:
    if db.bind.dialect.name == "postgresql":
        document = func.to_tsvector(
            literal_column("'simple'"),
            func.coalesce(ExternalEntity.display_name, literal_column("''")),
        )
        return or_(
            *[
                document.op("@@")(
                    func.plainto_tsquery(literal_column("'simple'"), term)
                )
                for term in search_terms
            ]
        )
    return or_(
        *[ExternalEntity.display_name.ilike(f"%{term}%") for term in search_terms]
    )


def _content_keyword_filter(db: Any, search_terms: tuple[str, ...]) -> Any:
    if db.bind.dialect.name == "postgresql":
        document = func.to_tsvector(
            literal_column("'simple'"),
            func.coalesce(ContentItem.title, literal_column("''"))
            + literal_column("' '")
            + func.coalesce(ContentItem.body, literal_column("''")),
        )
        return or_(
            *[
                document.op("@@")(
                    func.plainto_tsquery(literal_column("'simple'"), term)
                )
                for term in search_terms
            ]
        )
    return or_(
        *[
            or_(
                ContentItem.title.ilike(f"%{term}%"),
                ContentItem.body.ilike(f"%{term}%"),
            )
            for term in search_terms
        ]
    )


def _content_target_name(item: ContentItem) -> str:
    value = str(item.title or "").strip() or str(item.body or "").strip()
    return " ".join(value.split())[:96]


def _target_search_text(value: str) -> str:
    words = " ".join(str(value or "").split()).split(" ")
    return " ".join(words[:8])[:64]


def _lease_payload(
    row: AccountAction,
    *,
    target_id: str,
    external_id: str | None,
    display_name: str,
    canonical_url: str | None,
    entity_type: str,
    platform: str,
) -> dict[str, Any]:
    return {
        "available": True,
        "outcome": "leased",
        "account_action_id": str(row.id),
        "external_entity_id": target_id,
        "external_id": external_id,
        "display_name": display_name,
        "target_search_text": _target_search_text(display_name),
        "canonical_url": canonical_url,
        "entity_type": entity_type,
        "platform": platform,
        "source": str((row.target or {}).get("source") or "source_pool"),
    }


async def _reserve_target(
    db: Any,
    *,
    org_id: str,
    account_id: str,
    execution_id: str,
    step_id: str,
    action_type: str,
    platform: str,
    entity_type: str,
    action: str,
    target_id: str,
    display_name: str,
    source: str,
) -> AccountAction | None:
    target = {
        "action": action,
        "target_id": target_id,
        "target_type": entity_type,
        "name": display_name,
        "source": source,
    }
    action_key = stable_account_target_key(
        org_id=org_id,
        account_id=account_id,
        platform=platform,
        action_type=action_type,
        action=action,
        target_id=target_id,
    )
    row = await create_action(
        db,
        org_id=org_id,
        account_id=account_id,
        execution_id=execution_id,
        step_id=step_id,
        action_type=action_type,
        platform=platform,
        target=target,
        action_key=action_key,
    )
    if (
        str(row.execution_id) == execution_id
        and row.step_id == step_id
        and row.status
        in (
            AccountActionStatus.QUEUED.value,
            AccountActionStatus.RUNNING.value,
        )
    ):
        return row
    return None


async def lease_account_target(
    db: Any,
    *,
    identity: dict[str, str | None],
    platform: str,
    entity_type: str,
    action_type: str,
    action: str,
    statuses: Iterable[str] = ("approved", "active"),
    keywords: Any = None,
) -> dict[str, Any]:
    """Atomically reserve the next unused device target for one account."""
    org_id, account_id, execution_id, step_id = await _resolve_tenant(
        db, identity, require_ids=True
    )
    normalized_platform = str(platform or "").strip().casefold()
    normalized_type = str(entity_type or "").strip().casefold()
    normalized_action = str(action or "").strip().casefold()
    normalized_statuses = tuple(
        dict.fromkeys(
            status
            for item in statuses
            if (status := str(item or "").strip().casefold())
        )
    ) or ("approved", "active")
    search_terms = _keywords(keywords)

    execution = (
        await db.execute(
            select(Execution).where(
                Execution.id == execution_id,
                Execution.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if execution is None:
        raise ValueError("Target lease execution not found")
    device_id = (
        await db.execute(
            select(ExecutionDevice.device_id)
            .where(ExecutionDevice.execution_id == execution_id)
            .order_by(ExecutionDevice.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    with tenant_context(org_id):
        existing = (
            await db.execute(
                select(AccountAction)
                .where(
                    AccountAction.org_id == org_id,
                    AccountAction.account_id == account_id,
                    AccountAction.execution_id == execution_id,
                    AccountAction.step_id == step_id,
                    AccountAction.action_type == action_type,
                    AccountAction.platform == normalized_platform,
                    AccountAction.target["action"].as_string()
                    == normalized_action,
                    AccountAction.status.in_(
                        (
                            AccountActionStatus.QUEUED.value,
                            AccountActionStatus.RUNNING.value,
                        )
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing_target = existing.target or {}
            existing_target_id = str(existing_target.get("target_id") or "")
            if existing_target.get("source") == "content_item":
                content = (
                    await db.execute(
                        select(ContentItem).where(
                            ContentItem.org_id == org_id,
                            ContentItem.id == existing_target_id,
                        )
                    )
                ).scalar_one_or_none()
                if content is not None:
                    return _lease_payload(
                        existing,
                        target_id=str(content.id),
                        external_id=content.external_id,
                        display_name=_content_target_name(content),
                        canonical_url=content.url,
                        entity_type="post",
                        platform=normalized_platform,
                    )
            entity = (
                await db.execute(
                    select(ExternalEntity).where(
                        ExternalEntity.org_id == org_id,
                        ExternalEntity.id == existing_target_id,
                    )
                )
            ).scalar_one_or_none()
            if entity is not None:
                return _lease_payload(
                    existing,
                    target_id=str(entity.id),
                    external_id=entity.external_id,
                    display_name=entity.display_name,
                    canonical_url=entity.canonical_url,
                    entity_type=entity.entity_type,
                    platform=entity.platform,
                )

        used_target = (
            select(AccountAction.id)
            .where(
                AccountAction.org_id == org_id,
                AccountAction.account_id == account_id,
                AccountAction.platform == normalized_platform,
                AccountAction.action_type == action_type,
                AccountAction.target["action"].as_string() == normalized_action,
                AccountAction.target["target_id"].as_string() == ExternalEntity.id,
            )
            .exists()
        )
        if device_id:
            query = (
                select(DeviceTargetGroup, ExternalEntity)
                .join(
                    ExternalEntity,
                    (ExternalEntity.org_id == DeviceTargetGroup.org_id)
                    & (ExternalEntity.id == DeviceTargetGroup.external_entity_id),
                )
                .where(
                    DeviceTargetGroup.org_id == org_id,
                    DeviceTargetGroup.device_id == device_id,
                    ExternalEntity.platform == normalized_platform,
                    ExternalEntity.entity_type == normalized_type,
                    ExternalEntity.status.in_(normalized_statuses),
                    ~used_target,
                )
                .order_by(
                    DeviceTargetGroup.position.asc(),
                    ExternalEntity.last_seen_at.desc(),
                    DeviceTargetGroup.id.asc(),
                )
                .limit(25)
                .with_for_update(skip_locked=True, of=DeviceTargetGroup)
            )
            if search_terms:
                query = query.where(_keyword_filter(db, search_terms))

            rows = (await db.execute(query)).all()
            for _, entity in rows:
                row = await _reserve_target(
                    db,
                    org_id=org_id,
                    account_id=account_id,
                    execution_id=execution_id,
                    step_id=step_id,
                    action_type=action_type,
                    platform=normalized_platform,
                    entity_type=normalized_type,
                    action=normalized_action,
                    target_id=str(entity.id),
                    display_name=entity.display_name,
                    source="device_target_group",
                )
                if row is not None:
                    return _lease_payload(
                        row,
                        target_id=str(entity.id),
                        external_id=entity.external_id,
                        display_name=entity.display_name,
                        canonical_url=entity.canonical_url,
                        entity_type=entity.entity_type,
                        platform=entity.platform,
                    )

        # Posts are typically discovered at organization level rather than
        # assigned directly to a phone. Fall back to that pool after exhausting
        # explicit device assignments, while preserving account-level dedupe.
        pool_query = (
            select(ExternalEntity)
            .where(
                ExternalEntity.org_id == org_id,
                ExternalEntity.platform == normalized_platform,
                ExternalEntity.entity_type == normalized_type,
                ExternalEntity.status.in_(normalized_statuses),
                ~used_target,
            )
            .order_by(
                ExternalEntity.last_seen_at.desc(),
                ExternalEntity.id.asc(),
            )
            .limit(25)
            .with_for_update(skip_locked=True, of=ExternalEntity)
        )
        if search_terms:
            pool_query = pool_query.where(_keyword_filter(db, search_terms))
        for entity in (await db.execute(pool_query)).scalars():
            row = await _reserve_target(
                db,
                org_id=org_id,
                account_id=account_id,
                execution_id=execution_id,
                step_id=step_id,
                action_type=action_type,
                platform=normalized_platform,
                entity_type=normalized_type,
                action=normalized_action,
                target_id=str(entity.id),
                display_name=entity.display_name,
                source="org_source_pool",
            )
            if row is not None:
                return _lease_payload(
                    row,
                    target_id=str(entity.id),
                    external_id=entity.external_id,
                    display_name=entity.display_name,
                    canonical_url=entity.canonical_url,
                    entity_type=entity.entity_type,
                    platform=entity.platform,
                )

        if normalized_type == "post":
            used_content_target = (
                select(AccountAction.id)
                .where(
                    AccountAction.org_id == org_id,
                    AccountAction.account_id == account_id,
                    AccountAction.platform == normalized_platform,
                    AccountAction.action_type == action_type,
                    AccountAction.target["action"].as_string()
                    == normalized_action,
                    AccountAction.target["target_id"].as_string()
                    == ContentItem.id,
                )
                .exists()
            )
            content_query = (
                select(ContentItem)
                .where(
                    ContentItem.org_id == org_id,
                    ContentItem.platform == normalized_platform,
                    ContentItem.content_type.in_(("fb_post", "post")),
                    ContentItem.item_level == 0,
                    ContentItem.deleted_at.is_(None),
                    or_(ContentItem.title.is_not(None), ContentItem.body.is_not(None)),
                    ~used_content_target,
                )
                .order_by(ContentItem.extracted_at.desc(), ContentItem.id.asc())
                .limit(25)
                .with_for_update(skip_locked=True, of=ContentItem)
            )
            if search_terms:
                content_query = content_query.where(
                    _content_keyword_filter(db, search_terms)
                )
            for content in (await db.execute(content_query)).scalars():
                display_name = _content_target_name(content)
                if not display_name:
                    continue
                row = await _reserve_target(
                    db,
                    org_id=org_id,
                    account_id=account_id,
                    execution_id=execution_id,
                    step_id=step_id,
                    action_type=action_type,
                    platform=normalized_platform,
                    entity_type=normalized_type,
                    action=normalized_action,
                    target_id=str(content.id),
                    display_name=display_name,
                    source="content_item",
                )
                if row is not None:
                    return _lease_payload(
                        row,
                        target_id=str(content.id),
                        external_id=content.external_id,
                        display_name=display_name,
                        canonical_url=content.url,
                        entity_type="post",
                        platform=normalized_platform,
                    )

        return {
            "available": False,
            "outcome": "no_eligible_target",
            "platform": normalized_platform,
            "entity_type": normalized_type,
            "keywords": list(search_terms),
        }


def lease_account_target_blocking(
    *,
    identity: dict[str, str | None],
    platform: str,
    entity_type: str,
    action_type: str,
    action: str,
    statuses: Iterable[str] = ("approved", "active"),
    keywords: Any = None,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking

    async def lease() -> dict[str, Any]:
        async with activity_session() as db:
            return await lease_account_target(
                db,
                identity=identity,
                platform=platform,
                entity_type=entity_type,
                action_type=action_type,
                action=action,
                statuses=statuses,
                keywords=keywords,
            )

    return run_activity_coro_blocking(lease())
