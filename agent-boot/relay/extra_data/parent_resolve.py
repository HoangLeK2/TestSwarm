"""Resolve fb_comment parent content_hash for ingest (matches device_farm extraction_usecase)."""
from __future__ import annotations

from typing import Any

from relay.extra_data.writer import compute_content_hash, scope_content_hash


def _pick_exact_pid(
    posts: list[dict[str, Any]],
    field: str,
    value: str,
    *,
    dedupe_field: str,
) -> str | None:
    for post in posts:
        if not isinstance(post, dict):
            continue
        if str(post.get(field) or "").strip() == value:
            return compute_content_hash(post, dedupe_field=dedupe_field)
    return None


def resolve_fb_comment_parent_id(
    context: dict[str, Any],
    items: list[dict[str, Any]],
) -> tuple[str | None, bool]:
    """Return (parent_id, already_scoped).

    ``already_scoped`` is True when ``parent_id`` must not be re-scoped in the writer.
    """
    explicit = context.get("parent_id")
    if explicit:
        if context.get("parent_id_already_scoped"):
            return str(explicit), True
        return str(explicit), False

    scope = context.get("hash_scope") or context.get("execution_id")
    pid = str(context.get("parent_post_id") or "").strip()
    if not pid and items:
        for item in items:
            if isinstance(item, dict) and item.get("_type") != "post_stats":
                pid = str(item.get("parent_post_id") or "").strip()
                if pid:
                    break
    if not pid:
        return None, False

    pid_map = context.get("_post_id_map")
    if isinstance(pid_map, dict) and pid in pid_map:
        mapped = pid_map[pid]
        if mapped:
            return str(mapped), True

    posts = context.get("posts")
    if isinstance(posts, list) and posts:
        dedupe_field = str(
            context.get("_fb_posts_dedupe_field")
            or context.get("posts_dedupe_field")
            or "text"
        )
        for field in ("post_key", "stable_post_id", "fb_post_id", "_pid"):
            base = _pick_exact_pid(posts, field, pid, dedupe_field=dedupe_field)
            if base:
                return scope_content_hash(base, scope), True

    anchor = context.get("_active_comment_parent_anchor") or {}
    if isinstance(anchor, dict) and isinstance(posts, list) and posts:
        dedupe_field = str(
            context.get("_fb_posts_dedupe_field")
            or context.get("posts_dedupe_field")
            or "text"
        )
        a_author = str(anchor.get("author") or "").strip().lower()
        a_ts = str(anchor.get("timestamp") or "").strip().lower()
        a_prefix = str(anchor.get("text_prefix") or "").strip().lower()
        best_score = -1
        best_post: dict[str, Any] | None = None
        for post in posts:
            if not isinstance(post, dict):
                continue
            score = 0
            p_author = str(post.get("author") or "").strip().lower()
            p_ts = str(post.get("timestamp") or "").strip().lower()
            p_text = str(post.get("text") or "").strip().lower()
            if a_author and p_author and a_author == p_author:
                score += 2
            if a_ts and p_ts and a_ts == p_ts:
                score += 2
            if a_prefix and p_text and a_prefix[:120] in p_text:
                score += 2
            if score > best_score:
                best_score = score
                best_post = post
        if best_post is not None and best_score >= 2:
            base = compute_content_hash(best_post, dedupe_field=dedupe_field)
            return scope_content_hash(base, scope), True

    return None, False
