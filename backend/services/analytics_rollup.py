from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any


def _bucket(value: datetime, granularity: str):
    if granularity == "week":
        return (value - timedelta(days=value.weekday())).date()
    return value.date()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = round((len(ordered) - 1) * percentile)
    return ordered[idx]


def rollup_activity_rows(rows: list[dict[str, Any]], *, granularity: str = "day") -> list[dict[str, Any]]:
    buckets: dict[tuple[str, Any, str, str | None, str], dict[str, Any]] = {}
    latencies: dict[tuple[str, Any, str, str | None, str], list[float]] = defaultdict(list)
    for row in rows:
        created_at = row["created_at"]
        if not isinstance(created_at, datetime):
            continue
        event_type = str(row.get("action") or row.get("event_type") or "")
        resource_type = str(row.get("entity_type") or row.get("resource_type") or "event")
        resource_id = row.get("entity_id") or row.get("resource_id")
        key = (
            str(row.get("org_id") or ""),
            _bucket(created_at, granularity),
            resource_type,
            str(resource_id) if resource_id is not None else None,
            event_type,
        )
        item = buckets.setdefault(
            key,
            {
                "org_id": key[0],
                "bucket_date" if granularity == "day" else "week_start": key[1],
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id is not None else None,
                "event_type": event_type,
                "count": 0,
                "success_count": 0,
                "fail_count": 0,
                "latency_p50": None,
                "latency_p95": None,
            },
        )
        item["count"] += 1
        lower = event_type.lower()
        if "fail" in lower or "error" in lower or "offline" in lower:
            item["fail_count"] += 1
        else:
            item["success_count"] += 1
        details = row.get("details") or {}
        if isinstance(details, dict) and isinstance(details.get("duration_ms"), (int, float)):
            latencies[key].append(float(details["duration_ms"]))
    for key, values in latencies.items():
        buckets[key]["latency_p50"] = median(values)
        buckets[key]["latency_p95"] = _percentile(values, 0.95)
    return sorted(
        buckets.values(),
        key=lambda item: (item.get("bucket_date") or item.get("week_start"), item["resource_type"], item["event_type"]),
    )
