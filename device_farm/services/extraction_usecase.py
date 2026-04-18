from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging

from db.crud.content import update_content_stats
from db.database import activity_session
from services.content_store import save_content_item, _safe_int

log = logging.getLogger(__name__)


@dataclass
class PersistReport:
    saved_count: int = 0
    duplicate_count: int = 0
    error_count: int = 0
    processed_count: int = 0
    last_result: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "saved_count": self.saved_count,
            "duplicate_count": self.duplicate_count,
            "error_count": self.error_count,
            "processed_count": self.processed_count,
            "last_result": self.last_result or {},
        }


def _to_items(data: Any) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(data, str):
        return [{"text": data}], False
    if isinstance(data, dict):
        return [data], False
    if isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
        malformed = bool(data) and not items
        return items, malformed
    return [], False


def resolve_comment_parent_hash(
    ctx: dict[str, Any],
    parent_post_id: str | None,
) -> str | None:
    pid_key = parent_post_id
    return (ctx.get("_post_id_map", {}).get(pid_key) or ctx.get("_first_new_post_hash"))


async def update_parent_stats_if_available(
    *,
    content_hash: str | None,
    post_stats: dict[str, Any] | None,
) -> bool:
    if not content_hash or not post_stats:
        return False
    async with activity_session() as db:
        updated = await update_content_stats(
            db,
            content_hash=content_hash,
            likes_count=_safe_int(post_stats.get("reactions")),
            shares_count=_safe_int(post_stats.get("shares")),
        )
        if updated:
            await db.commit()
        return bool(updated)


async def persist_data_items(
    *,
    data: Any,
    data_var: str,
    offsets: dict[str, Any] | None = None,
    collection: str = "default",
    platform: str | None = None,
    content_type: str = "post",
    dedupe_field: str | None = None,
    tags: str | None = None,
    device_serial: str | None = None,
    campaign_id: str | None = None,
    execution_id: str | None = None,
    parent_id: str | None = None,
    item_level: int = 0,
    user_id: str | None = None,
) -> tuple[PersistReport, dict[str, Any]]:
    report = PersistReport()
    is_list_input = isinstance(data, list)
    items, malformed_list = _to_items(data)
    offset_map = dict(offsets or {})
    if malformed_list:
        report.error_count = 1
        return report, offset_map

    start_idx = int(offset_map.get(data_var, 0) or 0) if is_list_input else 0
    if is_list_input and start_idx > 0:
        items = items[start_idx:]
    if not items:
        return report, offset_map

    for item in items:
        try:
            result = await save_content_item(
                data=item,
                collection=collection,
                platform=platform,
                content_type=content_type,
                dedupe_field=dedupe_field,
                tags=tags,
                device_serial=device_serial,
                campaign_id=campaign_id,
                execution_id=execution_id,
                parent_id=parent_id,
                item_level=item_level,
                user_id=user_id,
            )
            report.last_result = result
            if result.get("saved"):
                report.saved_count += 1
            else:
                report.duplicate_count += 1
            report.processed_count += 1
        except Exception:
            report.error_count += 1
            log.warning(
                "persist_data_items failed: var=%s idx=%s collection=%s type=%s",
                data_var,
                start_idx + report.processed_count,
                collection,
                content_type,
                exc_info=True,
            )
            # Stop on first failing item to avoid skipping failed records in offset tracking.
            break

    if is_list_input:
        offset_map[data_var] = start_idx + report.processed_count
    return report, offset_map
