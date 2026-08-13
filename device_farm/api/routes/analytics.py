from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import activity_log_scope, data_owner_user_id
from api.schemas.analytics import (
    ActivityLogListOut,
    AnalyticsAdhocOut,
    AnalyticsSummaryOut,
    AnalyticsTimeseriesOut,
)
from db.models.analytics import MetricRollupDaily, MetricRollupWeekly
from db.models.activity import ActivityLog
from services.analytics_query import AnalyticsQueryError, analytics_query_from_payload
from services.activity_presenter import present_activity_logs
from services.user_action_audit import DEVICE_SCREEN_CONTROL_PATH_PARTS

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
    route_or_path_matches = or_(
        *[
            or_(
                ActivityLog.route_template.contains(part),
                ActivityLog.path.contains(part),
            )
            for part in DEVICE_SCREEN_CONTROL_PATH_PARTS
        ]
    )
    return stmt.where(
        ~(
            (ActivityLog.entity_type == "devices")
            & ActivityLog.action.startswith("user.devices.")
            & route_or_path_matches
        )
    )


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
    offset: int = 0,
    limit: int = 50,
):
    safe_limit = min(max(limit, 1), 100)
    scope = await activity_log_scope(db, user)
    q = select(ActivityLog).where(scope)
    count_q = select(func.count(ActivityLog.id)).where(scope)
    q = _exclude_device_screen_control_logs(q)
    count_q = _exclude_device_screen_control_logs(count_q)

    if action:
        q = q.where(ActivityLog.action == action)
        count_q = count_q.where(ActivityLog.action == action)
    if device_serial:
        q = q.where(ActivityLog.device_serial == device_serial)
        count_q = count_q.where(ActivityLog.device_serial == device_serial)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            q.order_by(ActivityLog.created_at.desc())
            .offset(max(offset, 0))
            .limit(safe_limit)
        )
    ).scalars().all()

    return ActivityLogListOut(
        total=total,
        offset=max(offset, 0),
        limit=safe_limit,
        activities=await present_activity_logs(db, list(rows)),
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
