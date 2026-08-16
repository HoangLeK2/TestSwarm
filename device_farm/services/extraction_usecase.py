from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging
import os
import asyncio

from db.crud.content import update_content_stats
from db.database import activity_session
from services.content_store import save_content_item, _safe_int, compute_content_hash

log = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _chunks(items: list[dict[str, Any]], size: int):
    size = max(1, size)
    for i in range(0, len(items), size):
        yield items[i:i + size]


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
    """Resolve the parent post's content_hash for a comment batch.

    Returns None when we cannot positively map ``parent_post_id`` to a post
    hash. Callers must treat None as "unknown parent" (save with parent_id=None)
    instead of silently attaching comments to a guessed post — this was the
    root cause of the "láy sai tè le" mismatch where ``_first_new_post_hash``
    (top-of-feed at last extract, NOT the actually-tapped post) was used as a
    fallback and linked comments to the wrong post.
    """
    ctx["_comment_parent_resolve_source"] = "none"
    pid_map = ctx.get("_post_id_map") or {}
    if parent_post_id and parent_post_id in pid_map:
        ctx["_comment_parent_resolve_source"] = "pid_map"
        return pid_map[parent_post_id]
    # Legacy key — only trust when it was written by ``social_open_comments``
    # (guaranteed to match the tapped post). Other writers set this to the
    # top-of-batch hash which may diverge from the tapped post, so when there's
    # any ambiguity we return None.
    explicit = ctx.get("_active_comment_parent_hash")
    if explicit:
        ctx["_comment_parent_resolve_source"] = "active_hash"
        return explicit
    # Fingerprint fallback from social_open_comments: robust against pid drift
    # when UI transitions lag and _comment_parent_pid is missing.
    anchor = ctx.get("_active_comment_parent_anchor") or {}
    posts = ctx.get("posts") or []
    if isinstance(anchor, dict) and isinstance(posts, list) and posts:
        dedupe_field = str(ctx.get("_posts_dedupe_field") or "post_key")

        def _pick_exact(field: str) -> str | None:
            v = str(anchor.get(field) or "").strip()
            if not v:
                return None
            for p in posts:
                if not isinstance(p, dict):
                    continue
                if str(p.get(field) or "").strip() == v:
                    ctx["_comment_parent_resolve_source"] = f"anchor_exact:{field}"
                    return compute_content_hash(p, dedupe_field=dedupe_field)
            return None

        for key in ("post_key", "stable_post_id", "fb_post_id"):
            h = _pick_exact(key)
            if h:
                return h

        # Soft score: author + timestamp + body prefix similarity.
        a_author = str(anchor.get("author") or "").strip().lower()
        a_ts = str(anchor.get("timestamp") or "").strip().lower()
        a_prefix = str(anchor.get("text_prefix") or "").strip().lower()
        best_score = -1
        best_post: dict[str, Any] | None = None
        for p in posts:
            if not isinstance(p, dict):
                continue
            score = 0
            p_author = str(p.get("author") or "").strip().lower()
            p_ts = str(p.get("timestamp") or "").strip().lower()
            p_text = str(p.get("text") or "").strip().lower()
            if a_author and p_author and a_author == p_author:
                score += 2
            if a_ts and p_ts and a_ts == p_ts:
                score += 2
            if a_prefix and p_text and a_prefix[:120] and a_prefix[:120] in p_text:
                score += 2
            if score > best_score:
                best_score = score
                best_post = p
        if best_post is not None and best_score >= 2:
            ctx["_comment_parent_resolve_source"] = "anchor_soft"
            return compute_content_hash(best_post, dedupe_field=dedupe_field)
    return None


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
            comments_count=_safe_int(post_stats.get("comments")),
        )
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
    account_id: str | None = None,
    parent_id: str | None = None,
    parent_id_already_scoped: bool = False,
    item_level: int = 0,
    user_id: str | None = None,
    batch_size: int | None = None,
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

    chunk_size = max(1, int(batch_size or _env_int("EXTRACT_AUTO_SAVE_BATCH_SIZE", 100)))
    for chunk in _chunks(items, chunk_size):
        async with activity_session() as db:
            chunk_failed = False
            for item in chunk:
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
                        account_id=account_id,
                        parent_id=parent_id,
                        parent_id_already_scoped=parent_id_already_scoped,
                        item_level=item_level,
                        user_id=user_id,
                        db=db,
                    )
                    report.last_result = result
                    if result.get("saved"):
                        report.saved_count += 1
                    else:
                        report.duplicate_count += 1
                    report.processed_count += 1
                except Exception:
                    report.error_count += 1
                    chunk_failed = True
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
        if chunk_failed:
            break
        if len(chunk) >= chunk_size and len(items) > chunk_size:
            await asyncio.sleep(float(os.environ.get("EXTRACT_AUTO_SAVE_CHUNK_PAUSE_S", "0.02")))

    if is_list_input:
        offset_map[data_var] = start_idx + report.processed_count
    return report, offset_map
