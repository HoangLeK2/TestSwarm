from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import false, func, literal, or_, select, union_all

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import activity_log_scope, data_owner_user_id
from api.schemas.analytics import (
    ActivityLogOut,
    ActivityLogListOut,
    AnalyticsAdhocOut,
    AnalyticsSummaryOut,
    AnalyticsTimeseriesOut,
)
from db.models.analytics import MetricRollupDaily, MetricRollupWeekly
from db.models.activity import ActivityLog
from db.models.account import Account
from db.models.account_action import AccountAction
from db.models.account_event import AccountEvent
from services.analytics_query import AnalyticsQueryError, analytics_query_from_payload
from services.activity_presenter import present_activity_logs
from services.user_action_audit import (
    DEVICE_SCREEN_CONTROL_PATH_PARTS,
    MEDIA_PREVIEW_PATH_PREFIXES,
)
from tenancy.context import tenant_context

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_DATE", "field": name}) from exc


def _day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, time.min, tzinfo=timezone.utc),
        datetime.combine(end, time.max, tzinfo=timezone.utc),
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(token in key.lower() for token in ("token", "secret", "password", "authorization", "api_key")):
                out[key] = "[REDACTED]"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _exclude_device_screen_control_logs(stmt):
    device_route_or_path_matches = or_(
        *[
            or_(
                ActivityLog.route_template.contains(part),
                ActivityLog.path.contains(part),
            )
            for part in DEVICE_SCREEN_CONTROL_PATH_PARTS
        ]
    )
    media_route_or_path_matches = or_(
        *[
            or_(
                ActivityLog.route_template.startswith(prefix),
                ActivityLog.path.startswith(prefix),
            )
            for prefix in MEDIA_PREVIEW_PATH_PREFIXES
        ]
    )
    return stmt.where(
        ~(
            (
                (ActivityLog.entity_type == "devices")
                & ActivityLog.action.startswith("user.devices.")
                & device_route_or_path_matches
            )
            | (
                (ActivityLog.entity_type == "media")
                & ActivityLog.action.startswith("user.media.")
                & media_route_or_path_matches
            )
            | ActivityLog.action.startswith("ws.")
        )
    )


def _account_visibility_filter(user: CurrentUser):
    org_id = getattr(user, "org_id", None)
    if org_id:
        return Account.org_id == org_id
    return Account.user_id == data_owner_user_id(user)


def _account_event_base(user: CurrentUser):
    return (
        select(AccountEvent)
        .join(Account, Account.id == AccountEvent.account_id)
        .where(_account_visibility_filter(user))
    )


def _account_action_base(user: CurrentUser):
    """Scope the ledger by its own org_id when there is one.

    Tenancy used to run through a join on `accounts`, which kept
    account_actions.org_id out of the WHERE clause entirely — so no index on the
    table could serve this feed and the default view fell back to a sequential
    scan. The table is tenant-scoped and carries org_id itself.

    It is also the more truthful predicate for an audit trail: an action belongs
    to the org it ran under, not to whichever org owns the account today. Only
    the org-less caller still needs the join, since it filters on the owner.
    """
    org_id = getattr(user, "org_id", None)
    if org_id:
        return select(AccountAction).where(AccountAction.org_id == org_id)
    return (
        select(AccountAction)
        .join(Account, Account.id == AccountAction.account_id)
        .where(_account_visibility_filter(user))
    )


def _apply_account_filters(
    stmt,
    *,
    account_id: str | None,
    device_serial: str | None,
):
    if account_id:
        stmt = stmt.where(Account.id == account_id)
    if device_serial:
        stmt = stmt.where(AccountEvent.device_serial == device_serial)
    return stmt


def _apply_account_action_filters(
    stmt,
    *,
    account_id: str | None,
    action: str | None,
    device_serial: str | None,
):
    if account_id:
        # AccountAction.account_id, not Account.id: the org-scoped base no longer
        # joins `accounts`, and this column is the same value anyway.
        stmt = stmt.where(AccountAction.account_id == account_id)
    if device_serial:
        # Used to return false() — the ledger had no device column, so filtering
        # by device silently dropped every account action. Rows written before
        # that column existed still have NULL and cannot match; the backfill
        # script fills them from execution_steps.
        stmt = stmt.where(AccountAction.device_serial == device_serial)
    if not action:
        return stmt
    if action == "account.action":
        return stmt
    prefix = "account.action."
    if action.startswith(prefix):
        return stmt.where(AccountAction.action_type == action[len(prefix) :])
    return stmt.where(false())


def _apply_account_event_filters(
    stmt,
    *,
    account_id: str | None,
    action: str | None,
    device_serial: str | None,
):
    stmt = _apply_account_filters(
        stmt,
        account_id=account_id,
        device_serial=device_serial,
    )
    if action:
        stmt = stmt.where(AccountEvent.event_type == action)
    return stmt


def _account_label(account: Account) -> str:
    display = (account.display_name or "").strip()
    username = (account.username or "").strip()
    if display and username and display != username:
        return f"{display} ({username})"
    return display or username or account.id


def _account_event_out(row: AccountEvent, account: Account) -> ActivityLogOut:
    details = dict(row.details) if isinstance(row.details, dict) else {}
    details.update(
        {
            "source": "account_event",
            "account_id": row.account_id,
            "account_label": _account_label(account),
            "account_username": account.username,
            "account_platform": account.platform,
            "event_type": row.event_type,
        }
    )
    return ActivityLogOut(
        id=f"account_event:{row.id}",
        action=row.event_type,
        entity_type="account",
        entity_id=row.account_id,
        device_serial=row.device_serial,
        device_display=None,
        org_id=account.org_id,
        user_id=row.user_id or account.user_id,
        user_name=None,
        method=None,
        path=None,
        route_template=None,
        status_code=None,
        request_id=None,
        ip_address=None,
        user_agent=None,
        outcome=None,
        duration_ms=None,
        details=_redact(details),
        created_at=row.created_at,
    )


def _account_action_out(row: AccountAction, account: Account) -> ActivityLogOut:
    target = row.target if isinstance(row.target, dict) else {}
    result = row.result if isinstance(row.result, dict) else {}
    target_label = target.get("label") or target.get("name")
    failed = row.status in {"failed", "stale", "cancelled"}
    error_message = (
        result.get("error_message")
        or result.get("error")
        or (result.get("reason") if failed else None)
    )
    details = {
        "source": "account_action",
        "account_id": row.account_id,
        "account_label": _account_label(account),
        "account_username": account.username,
        "account_platform": account.platform,
        "action_type": row.action_type,
        "status": row.status,
        "target_type": target.get("target_type") or target.get("type"),
        "target_id": target.get("target_id") or target.get("id"),
        "target_label": (
            str(target_label)[:512] if target_label is not None else None
        ),
        "error_code": result.get("error_code")
        or (result.get("reason") if failed else None),
        "error_message": str(error_message)[:2048] if error_message is not None else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "execution_id": row.execution_id,
        "step_id": row.step_id,
        "device_id": row.device_id,
        # Audit evidence recorded at finalize time. No post URL: targets come
        # from the Android view hierarchy, which has no permalink — the post is
        # identified by target_id plus the snippet in target_label.
        "comment_text": result.get("comment_text"),
        "author_name": result.get("author_name"),
        "group_name": result.get("group_name"),
    }
    return ActivityLogOut(
        id=f"account_action:{row.id}",
        action=f"account.action.{row.action_type}",
        entity_type="account",
        entity_id=row.account_id,
        device_serial=row.device_serial,
        device_display=row.device_serial,
        org_id=account.org_id,
        user_id=account.user_id,
        user_name=None,
        method=None,
        path=None,
        route_template=None,
        status_code=None,
        request_id=None,
        ip_address=None,
        user_agent=None,
        outcome=(
            "error"
            if failed
            else "success"
            if row.status == "succeeded"
            else None
        ),
        duration_ms=None,
        details=_redact(details),
        created_at=row.updated_at or row.created_at,
    )


async def _load_account_feed_page(
    db: DB,
    user: CurrentUser,
    *,
    action: str | None,
    device_serial: str | None,
    account_id: str | None,
    offset: int,
    limit: int,
    activity_stmt,
) -> tuple[int, list[ActivityLogOut]]:
    org_id = getattr(user, "org_id", None)
    with tenant_context(org_id):
        activity_keys = activity_stmt.with_only_columns(
            literal("activity").label("source"),
            ActivityLog.id.label("row_id"),
            ActivityLog.created_at.label("created_at"),
        )
        account_event_stmt = _apply_account_event_filters(
            _account_event_base(user),
            account_id=account_id,
            action=action,
            device_serial=device_serial,
        )
        account_action_stmt = _apply_account_action_filters(
            _account_action_base(user),
            account_id=account_id,
            action=action,
            device_serial=device_serial,
        )
        account_event_keys = account_event_stmt.with_only_columns(
            literal("account_event").label("source"),
            AccountEvent.id.label("row_id"),
            AccountEvent.created_at.label("created_at"),
        )
        account_action_keys = account_action_stmt.with_only_columns(
            literal("account_action").label("source"),
            AccountAction.id.label("row_id"),
            AccountAction.updated_at.label("created_at"),
        )

        feed = union_all(
            activity_keys,
            account_event_keys,
            account_action_keys,
        ).subquery()
        total = (
            await db.execute(select(func.count()).select_from(feed))
        ).scalar() or 0
        page_rows = (
            await db.execute(
                select(feed.c.source, feed.c.row_id)
                .order_by(feed.c.created_at.desc(), feed.c.row_id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()

        ids_by_source: dict[str, list[str]] = {
            "activity": [],
            "account_event": [],
            "account_action": [],
        }
        for source, row_id in page_rows:
            ids_by_source[str(source)].append(str(row_id))

        hydrated: dict[tuple[str, str], ActivityLogOut] = {}
        if ids_by_source["activity"]:
            rows = (
                await db.execute(
                    select(ActivityLog).where(
                        ActivityLog.id.in_(ids_by_source["activity"])
                    )
                )
            ).scalars().all()
            for item in await present_activity_logs(db, list(rows)):
                hydrated[("activity", item.id)] = item

        if ids_by_source["account_event"]:
            rows = (
                await db.execute(
                    select(AccountEvent, Account)
                    .join(Account, Account.id == AccountEvent.account_id)
                    .where(AccountEvent.id.in_(ids_by_source["account_event"]))
                )
            ).all()
            for event, account in rows:
                hydrated[("account_event", event.id)] = _account_event_out(
                    event,
                    account,
                )

        if ids_by_source["account_action"]:
            rows = (
                await db.execute(
                    select(AccountAction, Account)
                    .join(Account, Account.id == AccountAction.account_id)
                    .where(AccountAction.id.in_(ids_by_source["account_action"]))
                )
            ).all()
            for action_row, account in rows:
                hydrated[("account_action", action_row.id)] = _account_action_out(
                    action_row,
                    account,
                )

        return total, [
            hydrated[(str(source), str(row_id))]
            for source, row_id in page_rows
            if (str(source), str(row_id)) in hydrated
        ]


@router.get(
    "/activity",
    response_model=ActivityLogListOut,
    dependencies=[Depends(require_permission("analytics", "read"))],
)
async def list_activity(
    db: DB,
    user: CurrentUser,
    action: str | None = None,
    device_serial: str | None = None,
    account_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)
    scope = await activity_log_scope(db, user)
    q = select(ActivityLog).where(scope)
    q = _exclude_device_screen_control_logs(q)

    if action:
        q = q.where(ActivityLog.action == action)
    if device_serial:
        q = q.where(ActivityLog.device_serial == device_serial)
    if account_id:
        q = q.where(false())

    total, activities = await _load_account_feed_page(
        db,
        user,
        action=action,
        device_serial=device_serial,
        account_id=account_id.strip() if account_id else None,
        offset=safe_offset,
        limit=safe_limit,
        activity_stmt=q,
    )

    return ActivityLogListOut(
        total=total,
        offset=safe_offset,
        limit=safe_limit,
        activities=activities,
    )


@router.get(
    "/timeseries",
    response_model=AnalyticsTimeseriesOut,
    dependencies=[Depends(require_permission("analytics", "read"))],
)
async def timeseries(
    db: DB,
    user: CurrentUser,
    dimension: str = Query(..., pattern="^(device|campaign|platform|account|event_type)$"),
    resource_id: str | None = None,
    event_type: str | None = None,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    granularity: str = Query("day", pattern="^(day|week)$"),
):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail={"code": "ORG_CONTEXT_REQUIRED"})
    start = _parse_date(from_, "from")
    end = _parse_date(to, "to")
    if end < start:
        raise HTTPException(status_code=400, detail={"code": "INVALID_TIME_RANGE"})
    max_window = 90 if granularity == "day" else 7 * 52
    if (end - start).days > max_window:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "WINDOW_TOO_LARGE",
                "message": f"Max {max_window} days for {granularity} granularity",
            },
        )
    model = MetricRollupDaily if granularity == "day" else MetricRollupWeekly
    bucket_col = model.bucket_date if granularity == "day" else model.week_start
    resource_type = "event_type" if dimension == "event_type" else dimension
    stmt = select(model).where(
        model.org_id == org_id,
        bucket_col >= start,
        bucket_col <= end,
    )
    if dimension != "event_type":
        stmt = stmt.where(model.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(model.resource_id == resource_id)
    if event_type:
        stmt = stmt.where(model.event_type == event_type)
    rows = (
        await db.execute(
            stmt.order_by(bucket_col.asc(), model.resource_type.asc(), model.event_type.asc()).limit(1000)
        )
    ).scalars().all()
    points = []
    for row in rows:
        bucket = row.bucket_date if granularity == "day" else row.week_start
        points.append(
            {
                "date": bucket.isoformat(),
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "event_type": row.event_type,
                "count": row.count,
                "success_count": row.success_count,
                "fail_count": row.fail_count,
                "latency_p50": row.latency_p50,
                "latency_p95": row.latency_p95,
            }
        )
    return AnalyticsTimeseriesOut(points=points)


@router.get(
    "/summary",
    response_model=AnalyticsSummaryOut,
    dependencies=[Depends(require_permission("analytics", "read"))],
)
async def summary(db: DB, user: CurrentUser, window_days: int = 7):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail={"code": "ORG_CONTEXT_REQUIRED"})
    safe_days = min(max(window_days, 1), 90)
    start = date.today() - timedelta(days=safe_days - 1)
    stmt = select(
        func.coalesce(func.sum(MetricRollupDaily.count), 0),
        func.coalesce(func.sum(MetricRollupDaily.success_count), 0),
        func.coalesce(func.sum(MetricRollupDaily.fail_count), 0),
    ).where(MetricRollupDaily.org_id == org_id, MetricRollupDaily.bucket_date >= start)
    total, success, fail = (await db.execute(stmt)).one()
    total_i = int(total or 0)
    success_i = int(success or 0)
    fail_i = int(fail or 0)
    return AnalyticsSummaryOut(
        window_days=safe_days,
        total_count=total_i,
        success_count=success_i,
        fail_count=fail_i,
        success_rate=(success_i / total_i) if total_i else 0.0,
    )


@router.post(
    "/adhoc-query",
    response_model=AnalyticsAdhocOut,
    dependencies=[Depends(require_permission("analytics", "read"))],
)
async def adhoc_query(db: DB, user: CurrentUser, body: dict[str, Any] = Body(...)):
    try:
        query = analytics_query_from_payload(body)
    except AnalyticsQueryError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
    scope = await activity_log_scope(db, user)
    start_dt, end_dt = _day_bounds(query.from_date, query.to_date)
    stmt = select(ActivityLog).where(
        scope,
        ActivityLog.created_at >= start_dt,
        ActivityLog.created_at <= end_dt,
    )
    if "event_type" in query.filters:
        stmt = stmt.where(ActivityLog.action == str(query.filters["event_type"]))
    if "resource_type" in query.filters:
        stmt = stmt.where(ActivityLog.entity_type == str(query.filters["resource_type"]))
    if "resource_id" in query.filters:
        stmt = stmt.where(ActivityLog.entity_id == str(query.filters["resource_id"]))
    if "actor" in query.filters:
        stmt = stmt.where(ActivityLog.user_id == str(query.filters["actor"]))
    rows = (await db.execute(stmt.limit(query.limit))).scalars().all()
    grouped: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key_parts: list[Any] = []
        for dimension in query.dimensions:
            if dimension == "event_type":
                key_parts.append(row.action)
            elif dimension == "resource_type":
                key_parts.append(row.entity_type)
            elif dimension == "resource_id":
                key_parts.append(row.entity_id)
            elif dimension == "actor":
                key_parts.append(row.user_id)
            elif dimension == "day":
                key_parts.append(row.created_at.date().isoformat())
        key = tuple(key_parts)
        grouped[key] = grouped.get(key, 0) + 1
    out = []
    for key, count in sorted(grouped.items()):
        item = {dimension: key[idx] for idx, dimension in enumerate(query.dimensions)}
        item[query.metric] = count
        out.append(item)
    return AnalyticsAdhocOut(rows=out, row_count=len(out))


@router.get(
    "/audit/export",
    response_class=PlainTextResponse,
    dependencies=[Depends(require_permission("analytics", "read"))],
)
async def audit_export(
    db: DB,
    user: CurrentUser,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    action: str | None = None,
    actor: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
):
    start = _parse_date(from_, "from")
    end = _parse_date(to, "to")
    if (end - start).days > 90:
        raise HTTPException(status_code=400, detail={"code": "WINDOW_TOO_LARGE"})
    start_dt, end_dt = _day_bounds(start, end)
    scope = await activity_log_scope(db, user)
    stmt = select(ActivityLog).where(
        scope,
        ActivityLog.created_at >= start_dt,
        ActivityLog.created_at <= end_dt,
    )
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    if actor:
        stmt = stmt.where(ActivityLog.user_id == actor)
    if resource_type:
        stmt = stmt.where(ActivityLog.entity_type == resource_type)
    if resource_id:
        stmt = stmt.where(ActivityLog.entity_id == resource_id)
    rows = (
        await db.execute(stmt.order_by(ActivityLog.created_at.desc()).limit(100000))
    ).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "actor",
        "action",
        "resource_type",
        "resource_id",
        "timestamp",
        "source_module",
        "request_id",
        "details",
    ])
    for row in rows:
        writer.writerow(
            [
                row.user_id or "",
                row.action,
                row.entity_type or "",
                row.entity_id or "",
                row.created_at.isoformat() if row.created_at else "",
                (row.details or {}).get("source_module", ""),
                row.request_id or "",
                _redact(row.details or {}),
            ]
        )
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")
