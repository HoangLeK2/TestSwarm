"""HTTP XML ingest for phone/APK extra-data snapshots."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import time
from typing import Any

from relay.extra_data.writer import ContentItemWriter, build_content_item_row
from relay.extra_data.writer import compute_content_hash, scope_content_hash
from relay.extra_data.entity_writer import ExternalEntityWriter

logger = logging.getLogger("relay.extra_data")

_MULTI_PLATFORM_POST_STRATEGIES = {"ig_posts", "tiktok_posts", "linkedin_posts", "auto_posts"}
_MULTI_PLATFORM_COMMENT_STRATEGIES = {"ig_comments", "tiktok_comments", "linkedin_comments", "auto_comments"}
_SUPPORTED_CONTENT_STRATEGIES = (
    {"fb_posts", "fb_comments", "text_nodes"}
    | _MULTI_PLATFORM_POST_STRATEGIES
    | _MULTI_PLATFORM_COMMENT_STRATEGIES
)
_SUPPORTED_ENTITY_STRATEGIES = {"fb_groups"}


def _build_post_id_map(items: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, str]:
    """Map Facebook post ids (_pid / fb_post_id) to scoped content_hash for comment parent linking."""
    dedupe_field = str(
        context.get("posts_dedupe_field")
        or context.get("_fb_posts_dedupe_field")
        or context.get("dedupe_field")
        or "text"
    )
    scope = context.get("hash_scope") or context.get("execution_id")
    mapping: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("_type") == "post_stats":
            continue
        pid = str(item.get("_pid") or item.get("fb_post_id") or "").strip()
        if not pid:
            continue
        base = compute_content_hash(item, dedupe_field=dedupe_field)
        scoped = scope_content_hash(base, scope)
        if scoped:
            mapping[pid] = scoped
            for variant in item.get("_source_variants") or []:
                if not isinstance(variant, dict):
                    continue
                variant_pid = str(
                    variant.get("_pid") or variant.get("fb_post_id") or ""
                ).strip()
                if variant_pid:
                    mapping[variant_pid] = scoped
    return mapping


def _latest_post_stats(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for item in items:
        if isinstance(item, dict) and item.get("_type") == "post_stats":
            latest = item
    if latest is None:
        return None
    stats: dict[str, Any] = {}
    for src, dst in (
        ("reactions", "reactions"),
        ("likes", "reactions"),
        ("likes_count", "reactions"),
        ("comments", "comments"),
        ("comment_count", "comments"),
        ("comments_count", "comments"),
        ("shares", "shares"),
        ("shares_count", "shares"),
    ):
        value = latest.get(src)
        if value is not None and str(value).strip() != "":
            stats[dst] = value
    return stats or None


def _text_node_items(xml: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    items = [
        {"text": text, "body": text, "content_type": "text"}
        for node in root.iter()
        if (text := (node.get("text") or "").strip())
    ]
    return items, {"reason_code": "ok", "texts_returned": len(items)}


def _multi_platform_items(
    strategy: str,
    xml: str,
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from lxml import etree

    from relay.extra_data.parsers.platform_detector import detect_from_hierarchy, detect_parser

    root = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    is_comments = strategy in _MULTI_PLATFORM_COMMENT_STRATEGIES
    parser = None
    package_name = str(context.get("package_name") or context.get("current_package") or "").strip()
    if strategy.startswith("auto_"):
        parser = detect_parser(package_name) if package_name else None
        if parser is None:
            parser = detect_from_hierarchy(root)
    else:
        platform_code = strategy.split("_", 1)[0]
        pkg_map = {
            "ig": "com.instagram.android",
            "tiktok": "com.zhiliaoapp.musically",
            "linkedin": "com.linkedin.android",
        }
        parser = detect_parser(pkg_map.get(platform_code, ""))

    if parser is None:
        return [], {
            "reason_code": "platform_parser_not_found",
            "strategy": strategy,
            "package_name": package_name,
        }

    if is_comments:
        post_key = str(context.get("post_key") or context.get("parent_id") or context.get("parent_post_id") or "")
        parsed = parser.parse_comments(root, post_key)
    else:
        parsed = parser.parse_posts(root)
    items = [item.to_dict() for item in parsed]
    return items, {
        "reason_code": "ok",
        "platform": parser.platform,
        "items_returned": len(items),
    }


def _parse_items(strategy: str, xml: str, context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if strategy == "fb_groups":
        from relay.extra_data.parsers.facebook.group_pipeline import (
            parse_group_search_results,
        )

        return parse_group_search_results(xml)
    if strategy == "fb_comment_filter_next":
        from relay.extra_data.parsers.facebook.comment_filter import resolve_comment_filter_next_tap

        return [], resolve_comment_filter_next_tap(xml, context)
    if strategy in {"fb_comment_target", "fb_comment_target_tap"}:
        from relay.extra_data.parsers.facebook import resolve_comment_targets_from_xml
        from relay.extra_data.parsers.facebook.comment_pipeline import (
            diagnose_comment_target_resolution,
        )
        from relay.extra_data.parsers.facebook.parser import _hierarchy_is_fb_comment_sheet, _parse_xml

        root = _parse_xml(xml)
        if root is not None and _hierarchy_is_fb_comment_sheet(root):
            return [], {
                "reason_code": "already_on_comment_sheet",
                "target": None,
                "alternates": [],
                "candidate_count": 0,
            }

        # Rank Comment buttons by proximity to mid-screen so a feed with several
        # visible "Bình luận" rows never silently latches onto the wrong post.
        locked_anchor = context.get("_active_comment_parent_anchor")
        if not isinstance(locked_anchor, dict) or not locked_anchor:
            locked_anchor = None
        top, ranked = resolve_comment_targets_from_xml(
            xml,
            locked_anchor=locked_anchor,
        )
        if not top:
            diag = diagnose_comment_target_resolution(xml)
            return [], {
                "reason_code": "comment_button_not_found",
                "target": None,
                "alternates": [],
                "candidate_count": 0,
                "resolution_diagnostic": diag,
            }
        dedupe_field = str(
            context.get("posts_dedupe_field")
            or context.get("_fb_posts_dedupe_field")
            or context.get("dedupe_field")
            or "text"
        )
        scope = context.get("hash_scope") or context.get("execution_id")

        def _target_from(cand: dict[str, Any]) -> dict[str, Any]:
            post = cand["post"]
            bnds = cand["comment_bounds"]
            base_hash = compute_content_hash(post, dedupe_field=dedupe_field)
            text_prefix = (
                post.get("text")
                or post.get("body")
                or post.get("content")
                or post.get("message")
                or post.get("caption")
                or post.get("description")
                or post.get("image_desc")
                or ""
            )
            return {
                "bounds": list(bnds),
                "u2_click": cand.get("comment_u2_click"),
                "parent_post_bounds": (
                    list(cand["parent_post_bounds"])
                    if cand.get("parent_post_bounds")
                    else None
                ),
                "pid": post.get("_pid"),
                "parent_base_hash": base_hash,
                "parent_id": scope_content_hash(base_hash, scope),
                "post_key": post.get("post_key"),
                "stable_post_id": post.get("stable_post_id"),
                "fb_post_id": post.get("fb_post_id"),
                "author": post.get("author"),
                "timestamp": post.get("timestamp"),
                "text_prefix": str(text_prefix)[:220],
                "score": cand.get("score"),
                "score_breakdown": cand.get("breakdown"),
                "feed_item_index": cand.get("feed_item_index"),
            }

        target = _target_from(top)
        alternates = [_target_from(c) for c in ranked[1:]]
        return [], {
            "reason_code": "ok",
            "target": target,
            "alternates": alternates,
            "candidate_count": len(ranked),
        }
    if strategy == "fb_posts":
        from relay.extra_data.parsers.facebook import parse_fb_posts_from_xml_with_diagnostic

        return parse_fb_posts_from_xml_with_diagnostic(
            xml,
            source_index=int(context.get("source_index") or 0),
        )
    if strategy == "fb_comments":
        from relay.extra_data.parsers.facebook import parse_fb_comments_from_xml_with_diagnostic

        kwargs: dict[str, Any] = {
            "parent_post_id": context.get("parent_post_id") or context.get("parent_id"),
            "max_items": int(context.get("max_items") or 400),
        }
        parent_post_anchor = (
            context.get("_active_comment_parent_anchor")
            if isinstance(context.get("_active_comment_parent_anchor"), dict)
            else context.get("parent_post_anchor")
        )
        if isinstance(parent_post_anchor, dict) and parent_post_anchor:
            try:
                import inspect

                sig = inspect.signature(parse_fb_comments_from_xml_with_diagnostic)
                supports_anchor = (
                    "parent_post_anchor" in sig.parameters
                    or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    )
                )
            except (TypeError, ValueError):
                supports_anchor = True
            if supports_anchor:
                kwargs["parent_post_anchor"] = parent_post_anchor
        return parse_fb_comments_from_xml_with_diagnostic(
            xml,
            **kwargs,
        )
    if strategy == "text_nodes":
        return _text_node_items(xml)
    if strategy in _MULTI_PLATFORM_POST_STRATEGIES or strategy in _MULTI_PLATFORM_COMMENT_STRATEGIES:
        return _multi_platform_items(strategy, xml, context)
    return [], {"reason_code": "unsupported_strategy", "strategy": strategy}


def _xml_snapshots_from_payload(payload: dict[str, Any], primary_xml: str) -> list[str]:
    snapshots: list[str] = []
    seen: set[str] = set()

    def add_snapshot(value: Any) -> None:
        if not isinstance(value, str) or "<hierarchy" not in value:
            return
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if digest in seen:
            return
        seen.add(digest)
        snapshots.append(value)

    add_snapshot(primary_xml)
    raw_snapshots = payload.get("xml_snapshots")
    if isinstance(raw_snapshots, list):
        for snapshot in raw_snapshots:
            add_snapshot(snapshot)
    return snapshots


def _comment_dedupe_key(item: dict[str, Any]) -> str:
    explicit = str(item.get("comment_key") or item.get("id") or item.get("content_hash") or "").strip()
    if explicit:
        return explicit
    return "|".join(
        str(item.get(k) or "").strip().lower()
        for k in ("author", "text", "body", "timestamp")
    )


def _fb_comment_item_has_body(item: dict[str, Any]) -> bool:
    for key in ("text", "body", "content", "message", "caption", "description", "image_desc"):
        if str(item.get(key) or "").strip():
            return True
    return False


def merge_fb_comment_frames(
    frame_results: list[tuple[list[dict[str, Any]], dict[str, Any]]],
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    merged_comments: list[dict[str, Any]] = []
    seen: set[str] = set()
    latest_stats: dict[str, Any] | None = None
    frame_codes: list[str] = []
    last_diagnostic: dict[str, Any] = {"reason_code": "no_snapshots"}
    dropped_empty_comments = 0

    for items, diagnostic in frame_results:
        last_diagnostic = diagnostic
        frame_codes.append(str(diagnostic.get("reason_code") or "unknown"))
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("_type") == "post_stats":
                latest_stats = item
                continue
            if not _fb_comment_item_has_body(item):
                dropped_empty_comments += 1
                continue
            key = _comment_dedupe_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged_comments.append(item)
            if len(merged_comments) >= max_items:
                break
        if len(merged_comments) >= max_items:
            break

    merged: list[dict[str, Any]] = []
    if latest_stats is not None:
        merged.append(latest_stats)
    merged.extend(merged_comments[:max_items])
    diagnostic = {
        **last_diagnostic,
        "reason_code": "ok" if merged_comments or latest_stats else last_diagnostic.get("reason_code", "no_comments"),
        "snapshot_count": len(frame_results),
        "frame_reason_codes": frame_codes,
        "comments_returned": len(merged_comments[:max_items]),
        "has_header_stats": latest_stats is not None,
    }
    if dropped_empty_comments:
        diagnostic["dropped_empty_comments"] = dropped_empty_comments
    return merged, diagnostic


def _parse_fb_comment_snapshots(
    snapshots: list[str],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Match single-snapshot parse default (400) so multi-scroll runs are not capped at 50.
    max_items = int(context.get("max_items") or 400)
    frame_results: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    for idx, snapshot in enumerate(snapshots):
        frame_context = {**context, "source_index": idx}
        items, diagnostic = _parse_items("fb_comments", snapshot, frame_context)
        frame_results.append((items, diagnostic))
    items, diagnostic = merge_fb_comment_frames(frame_results, max_items=max_items)
    return items, _annotate_comment_target_diagnostic(
        diagnostic,
        context,
        comments_returned=len(
            [item for item in items if item.get("_type") != "post_stats"]
        ),
    )


def _annotate_comment_target_diagnostic(
    diagnostic: dict[str, Any],
    context: dict[str, Any],
    *,
    comments_returned: int,
) -> dict[str, Any]:
    annotated = dict(diagnostic)
    target = int(context.get("comment_target_effective") or 0)
    post_comment_count = context.get("post_comment_count")
    target_is_known = (
        isinstance(post_comment_count, int)
        and not isinstance(post_comment_count, bool)
        and post_comment_count > 0
    ) or context.get("comment_require_target_without_count") is True
    comments_returned = int(comments_returned)
    annotated["comments_returned"] = comments_returned
    if target > 0 and target_is_known:
        annotated["comment_target"] = target
        annotated["coverage_ratio"] = min(1.0, comments_returned / target)
        for key in (
            "post_comment_count",
            "comment_scroll_stopped_reason",
            "comment_scroll_passes_effective",
            "comment_crawl_mode_effective",
            "comment_coverage_collected",
        ):
            if context.get(key) is not None:
                annotated[key] = context[key]
        if comments_returned < target:
            annotated["reason_code"] = "partial_target"
    return annotated


def _parse_fb_post_snapshots(
    snapshots: list[str],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from relay.extra_data.parsers.facebook.post_reconciliation import (
        reconcile_fb_post_frames,
    )

    frame_items: list[list[dict[str, Any]]] = []
    frame_codes: list[str] = []
    frame_posts_returned: list[int] = []
    last_diagnostic: dict[str, Any] = {"reason_code": "no_snapshots"}

    for idx, snapshot in enumerate(snapshots):
        frame_context = {**context, "source_index": idx}
        items, diagnostic = _parse_items("fb_posts", snapshot, frame_context)
        last_diagnostic = diagnostic
        frame_codes.append(str(diagnostic.get("reason_code") or "unknown"))
        frame_posts_returned.append(int(diagnostic.get("posts_returned") or len(items)))
        frame_items.append([item for item in items if isinstance(item, dict)])

    opened = _opened_post_from_context(context)
    deduped, reconciliation = reconcile_fb_post_frames(
        frame_items,
        opened_post=opened,
    )
    diagnostic = {
        **last_diagnostic,
        **reconciliation,
        "reason_code": "ok" if deduped else last_diagnostic.get("reason_code", "no_posts"),
        "snapshot_count": len(snapshots),
        "frame_reason_codes": frame_codes,
        "frame_posts_returned": frame_posts_returned,
        "posts_returned": len(deduped),
    }
    return deduped, diagnostic


def _parse_fb_group_snapshots(
    snapshots: list[str],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    def merge_non_empty(existing: Any, incoming: Any) -> Any:
        if isinstance(existing, dict) and isinstance(incoming, dict):
            merged_value = dict(existing)
            for key, value in incoming.items():
                merged_value[key] = merge_non_empty(merged_value.get(key), value)
            return merged_value
        if incoming in (None, "", [], {}):
            return existing
        return incoming

    max_items = max(1, int(context.get("max_items") or 500))
    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    frame_codes: list[str] = []
    frame_groups_returned: list[int] = []
    last_diagnostic: dict[str, Any] = {"reason_code": "no_snapshots"}

    for snapshot in snapshots:
        items, diagnostic = _parse_items("fb_groups", snapshot, context)
        last_diagnostic = diagnostic
        frame_codes.append(str(diagnostic.get("reason_code") or "unknown"))
        frame_groups_returned.append(
            int(diagnostic.get("groups_returned") or len(items))
        )
        for item in items:
            identity_key = str(item.get("identity_key") or "").strip()
            if not identity_key:
                continue
            position = positions.get(identity_key)
            if position is None:
                if len(merged) >= max_items:
                    continue
                positions[identity_key] = len(merged)
                merged.append({**item, "rank": len(merged) + 1})
                continue
            first_rank = merged[position].get("rank")
            merged[position] = merge_non_empty(merged[position], item)
            merged[position]["rank"] = first_rank

    diagnostic = {
        **last_diagnostic,
        "reason_code": (
            "ok"
            if merged
            else last_diagnostic.get("reason_code", "no_groups")
        ),
        "snapshot_count": len(snapshots),
        "frame_reason_codes": frame_codes,
        "frame_groups_returned": frame_groups_returned,
        "groups_returned": len(merged),
    }
    return merged, diagnostic


def _trusted_preparsed_fb_comments(
    strategy: str,
    context: dict[str, Any],
    payload: dict[str, Any],
    xml: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    if strategy != "fb_comments" or context.get("agent_boot_preparsed_comments") is not True:
        return None
    preparsed = payload.get("preparsed")
    if not isinstance(preparsed, dict):
        return None
    raw_items = preparsed.get("items")
    if not isinstance(raw_items, list):
        return None
    payload_hashes = payload.get("snapshot_hashes")
    if not isinstance(payload_hashes, list) or not payload_hashes:
        return None
    expected_hashes = [str(value).strip() for value in payload_hashes]
    if any(not value for value in expected_hashes):
        return None
    try:
        payload_snapshot_count = int(payload.get("snapshot_count"))
        preparsed_snapshot_count = int(preparsed.get("snapshot_count"))
    except (TypeError, ValueError):
        return None
    if (
        payload_snapshot_count != len(expected_hashes)
        or preparsed_snapshot_count != payload_snapshot_count
    ):
        return None
    xml_sha256 = str(payload.get("xml_sha256") or "").strip()
    actual_xml_sha256 = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    if xml_sha256 != actual_xml_sha256 or expected_hashes[0] != xml_sha256:
        return None
    raw_hashes = preparsed.get("snapshot_hashes")
    if not isinstance(raw_hashes, list) or [
        str(value).strip() for value in raw_hashes
    ] != expected_hashes:
        return None
    raw_diagnostic = preparsed.get("diagnostic")
    diagnostic = dict(raw_diagnostic) if isinstance(raw_diagnostic, dict) else {}
    dropped_empty_comments = 0
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        if item.get("_type") == "post_stats" or _fb_comment_item_has_body(item):
            items.append(item)
        else:
            dropped_empty_comments += 1
    comment_count = len([item for item in items if item.get("_type") != "post_stats"])
    diagnostic.setdefault("reason_code", "ok" if items else "no_comments")
    diagnostic.setdefault("comments_returned", comment_count)
    diagnostic["comments_returned"] = comment_count
    if dropped_empty_comments:
        diagnostic["dropped_empty_comments"] = dropped_empty_comments
    for key in ("snapshot_count", "xml_bytes"):
        value = preparsed.get(key)
        if value is None:
            continue
        try:
            diagnostic[key] = int(value)
        except (TypeError, ValueError):
            pass
    diagnostic["preparsed"] = True
    return items, _annotate_comment_target_diagnostic(
        diagnostic,
        context,
        comments_returned=comment_count,
    )


def _parse_payload_items(
    strategy: str,
    xml: str,
    context: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    snapshots = _xml_snapshots_from_payload(payload, xml)
    if strategy == "fb_comments":
        preparsed = _trusted_preparsed_fb_comments(strategy, context, payload, xml)
        if preparsed is not None:
            items, diagnostic = preparsed
            return items, diagnostic, snapshots
        if len(snapshots) > 1:
            items, diagnostic = _parse_fb_comment_snapshots(snapshots, context)
            return items, diagnostic, snapshots
    if strategy == "fb_posts" and len(snapshots) > 1:
        items, diagnostic = _parse_fb_post_snapshots(snapshots, context)
        return items, diagnostic, snapshots
    if strategy == "fb_groups" and len(snapshots) > 1:
        items, diagnostic = _parse_fb_group_snapshots(snapshots, context)
        return items, diagnostic, snapshots
    items, diagnostic = _parse_items(strategy, xml, context)
    return items, diagnostic, snapshots


def _comment_parent_anchor(context: dict[str, Any]) -> dict[str, Any] | None:
    anchor = context.get("_active_comment_parent_anchor")
    if not isinstance(anchor, dict):
        return None
    clean: dict[str, Any] = {}
    for key in (
        "pid",
        "post_key",
        "stable_post_id",
        "fb_post_id",
        "author",
        "timestamp",
        "text_prefix",
    ):
        value = anchor.get(key)
        if value is not None and str(value).strip():
            clean[key] = value
    return clean or None


def _comment_parent_source(context: dict[str, Any]) -> str:
    anchor = context.get("_active_comment_parent_anchor")
    anchor_source = anchor.get("source") if isinstance(anchor, dict) else ""
    return str(
        context.get("parent_context_source")
        or context.get("_active_comment_parent_source")
        or anchor_source
        or ""
    ).strip()


def _has_verified_comment_parent_context(context: dict[str, Any]) -> bool:
    source = _comment_parent_source(context)
    session = context.get("_fb_comment_session")
    has_session = isinstance(session, dict) and bool(session.get("session_id"))
    if has_session:
        context_parent = str(context.get("parent_id") or "").strip()
        session_parent = str(session.get("parent_id") or "").strip()
        if context_parent != session_parent:
            return False
        context_pid = str(
            context.get("parent_post_id")
            or context.get("_fb_comment_parent_pid")
            or ""
        ).strip()
        session_pid = str(session.get("parent_post_id") or "").strip()
        if context_pid != session_pid:
            return False
    return bool(
        context.get("parent_id")
        and source in {"post_detail", "tap_fb_comment_button"}
        and (source == "tap_fb_comment_button" or has_session)
    )


def _requires_verified_comment_parent(context: dict[str, Any]) -> bool:
    if context.get("require_verified_parent") is not None:
        return bool(context.get("require_verified_parent"))
    return str(context.get("collection") or "").strip() == "fb_group_posts"


def _parsed_comment_parent_post_ids(items: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("_type") == "post_stats":
            continue
        pid = str(item.get("parent_post_id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def _drop_stale_comment_parent_context(
    context: dict[str, Any],
    items: list[dict[str, Any]],
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    """Prefer parser-observed parent PID over stale tap context for comment rows."""
    context_pid = str(
        context.get("parent_post_id")
        or context.get("_fb_comment_parent_pid")
        or ""
    ).strip()
    parsed_pids = _parsed_comment_parent_post_ids(items)
    if not context_pid or not parsed_pids or context_pid in parsed_pids:
        return context
    if _has_verified_comment_parent_context(context):
        diagnostic["parent_context_locked"] = True
        diagnostic["context_parent_post_id"] = context_pid
        diagnostic["parsed_parent_post_ids"] = parsed_pids
        return context

    corrected = dict(context)
    corrected.pop("parent_id", None)
    corrected.pop("parent_content_hash", None)
    corrected.pop("_active_comment_parent_hash", None)
    corrected.pop("_active_comment_parent_anchor", None)
    corrected.pop("_edge_comment_parent_base_hash", None)
    corrected["parent_id_already_scoped"] = False
    if len(parsed_pids) == 1:
        corrected["parent_post_id"] = parsed_pids[0]
        corrected["_fb_comment_parent_pid"] = parsed_pids[0]
    else:
        corrected.pop("parent_post_id", None)
        corrected.pop("_fb_comment_parent_pid", None)

    diagnostic["parent_context_corrected"] = True
    diagnostic["context_parent_post_id"] = context_pid
    diagnostic["parsed_parent_post_ids"] = parsed_pids
    logger.warning(
        "extra-data fb_comments parent context corrected: context_pid=%s parsed_pids=%s",
        context_pid,
        parsed_pids,
    )
    return corrected


def _with_comment_parent_context(
    items: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    parent_id: str | None,
) -> list[dict[str, Any]]:
    parent_post_id = str(
        context.get("parent_post_id")
        or context.get("_fb_comment_parent_pid")
        or ""
    ).strip()
    parent_hash = str(
        parent_id
        or context.get("_active_comment_parent_hash")
        or context.get("parent_content_hash")
        or ""
    ).strip()
    anchor = _comment_parent_anchor(context)
    parent_source = _comment_parent_source(context)
    force_context_parent = _has_verified_comment_parent_context(context)
    if not parent_post_id and not parent_hash and not anchor:
        return items

    enriched: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("_type") == "post_stats":
            enriched.append(item)
            continue
        row = dict(item)
        if parent_post_id and (force_context_parent or not row.get("parent_post_id")):
            existing_pid = str(row.get("parent_post_id") or "").strip()
            if force_context_parent and existing_pid and existing_pid != parent_post_id:
                row["parser_parent_post_id"] = existing_pid
            row["parent_post_id"] = parent_post_id
        if parent_hash and (force_context_parent or not row.get("parent_content_hash")):
            row["parent_content_hash"] = parent_hash
        if anchor and (force_context_parent or not row.get("parent_post_anchor")):
            row["parent_post_anchor"] = anchor
        if parent_source and not row.get("parent_context_source"):
            row["parent_context_source"] = parent_source
        enriched.append(row)
    return enriched


def _active_parent_post_payload(item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    parent_id = str(row.get("content_hash") or "").strip()
    if not parent_id:
        return None
    text_prefix = (
        item.get("text")
        or item.get("body")
        or item.get("content")
        or item.get("message")
        or item.get("caption")
        or item.get("description")
        or item.get("image_desc")
        or ""
    )
    payload = {
        "pid": item.get("_pid"),
        "parent_id": parent_id,
        "post_key": item.get("post_key"),
        "stable_post_id": item.get("stable_post_id"),
        "fb_post_id": item.get("fb_post_id"),
        "author": item.get("author"),
        "timestamp": item.get("timestamp"),
        "text_prefix": str(text_prefix)[:220],
    }
    return {key: value for key, value in payload.items() if value is not None and str(value).strip()}


def _opened_post_from_context(context: dict[str, Any]) -> dict[str, Any] | None:
    diagnostic = context.get("open_post_detail_diagnostic")
    if not isinstance(diagnostic, dict):
        return None
    opened = diagnostic.get("opened_post")
    if not isinstance(opened, dict):
        return None
    return opened


def _synthetic_post_from_opened_post(context: dict[str, Any]) -> dict[str, Any] | None:
    opened = _opened_post_from_context(context)
    if not opened:
        return None
    text = (
        opened.get("text")
        or opened.get("body")
        or opened.get("text_prefix")
        or ""
    )
    item = {
        "_pid": opened.get("pid"),
        "post_key": opened.get("post_key"),
        "stable_post_id": opened.get("stable_post_id"),
        "fb_post_id": opened.get("fb_post_id"),
        "author": opened.get("author"),
        "timestamp": opened.get("timestamp"),
        "text": text,
        "selection_reason": "opened_post_diagnostic",
    }
    cleaned = {key: value for key, value in item.items() if value is not None and str(value).strip()}
    has_identity = any(cleaned.get(key) for key in ("_pid", "post_key", "stable_post_id", "fb_post_id"))
    if not has_identity and not str(cleaned.get("text") or "").strip():
        return None
    return cleaned


def _post_matches_opened(item: dict[str, Any], opened: dict[str, Any]) -> bool:
    comparisons = (
        ("_pid", "pid"),
        ("post_key", "post_key"),
        ("stable_post_id", "stable_post_id"),
        ("fb_post_id", "fb_post_id"),
    )
    for item_key, opened_key in comparisons:
        item_value = str(item.get(item_key) or "").strip()
        opened_value = str(opened.get(opened_key) or "").strip()
        if item_value and opened_value and item_value == opened_value:
            return True
    for variant in item.get("_source_variants") or []:
        if isinstance(variant, dict) and _post_matches_opened(variant, opened):
            return True
    if _post_metadata_matches_opened(item, opened):
        return True
    return False


def _norm_match_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _post_match_text(item: dict[str, Any]) -> str:
    return _norm_match_text(
        item.get("text")
        or item.get("body")
        or item.get("content")
        or item.get("message")
        or item.get("caption")
        or item.get("description")
        or item.get("image_desc")
        or ""
    )


def _post_metadata_matches_opened(item: dict[str, Any], opened: dict[str, Any]) -> bool:
    opened_prefix = _norm_match_text(
        opened.get("text_prefix")
        or opened.get("text")
        or opened.get("body")
        or ""
    )
    item_text = _post_match_text(item)
    if len(opened_prefix) < 16 or len(item_text) < 16:
        return False
    if opened_prefix not in item_text and item_text not in opened_prefix:
        return False

    opened_author = _norm_match_text(opened.get("author"))
    item_author = _norm_match_text(item.get("author"))
    if opened_author and item_author and opened_author != item_author:
        return False

    opened_timestamp = _norm_match_text(opened.get("timestamp"))
    item_timestamp = _norm_match_text(item.get("timestamp"))
    if opened_timestamp and item_timestamp and opened_timestamp != item_timestamp:
        return False
    return True


def _active_parent_from_opened_post(
    context: dict[str, Any],
    row_items: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    opened = _opened_post_from_context(context)
    if not opened:
        return None
    for item, row in zip(row_items, rows):
        if _post_matches_opened(item, opened):
            payload = _active_parent_post_payload(item, row)
            if payload is None:
                return None
            canonicalized = item.get("_canonicalized_from_detail") is True
            for key in ("pid", "post_key", "stable_post_id", "fb_post_id", "author", "timestamp"):
                value = opened.get(key)
                if (
                    value is not None
                    and str(value).strip()
                    and (canonicalized or key not in payload)
                ):
                    payload[key] = value
            if canonicalized:
                opened_text = (
                    opened.get("text_prefix")
                    or opened.get("text")
                    or opened.get("body")
                )
                if opened_text is not None and str(opened_text).strip():
                    payload["text_prefix"] = str(opened_text)[:220]
            return payload
    return None


class ExtraDataIngestServer:
    def __init__(self) -> None:
        self._host = os.getenv("AGENT_BOOT_EXTRA_HOST", "0.0.0.0")
        self._port = int(os.getenv("AGENT_BOOT_EXTRA_PORT", "8765"))
        self._max_bytes = max(1024, int(os.getenv("AGENT_BOOT_XML_MAX_BYTES", str(8 * 1024 * 1024))))
        self._token = os.getenv("AGENT_BOOT_EXTRA_TOKEN", "").strip()
        self._allow_unauth = os.getenv("AGENT_BOOT_EXTRA_ALLOW_UNAUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        self._writer = ContentItemWriter()
        self._entity_writer = ExternalEntityWriter(self._writer._ensure_pool)
        default_workers = max(2, min(4, os.cpu_count() or 2))
        workers = max(1, int(os.getenv("AGENT_BOOT_XML_PARSE_WORKERS", str(default_workers))))
        self._parse_sem = asyncio.Semaphore(workers)
        self._serial_locks: dict[str, asyncio.Lock] = {}
        self._server: asyncio.AbstractServer | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self._host, self._port)
        logger.info("extra-data ingest listening on %s", self.base_url)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        await self._writer.close()

    def _lock_for_serial(self, serial: str) -> asyncio.Lock:
        lock = self._serial_locks.get(serial)
        if lock is None:
            lock = asyncio.Lock()
            self._serial_locks[serial] = lock
        return lock

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            if len(header) > 64 * 1024:
                await self._send_response(writer, 431, {"ok": False, "error": "headers_too_large"})
                return
            header_text = header.decode("iso-8859-1", errors="replace")
            first = header_text.splitlines()[0] if header_text.splitlines() else ""
            parts = first.split()
            method, path = (parts[0], parts[1]) if len(parts) >= 2 else ("", "")
            headers: dict[str, str] = {}
            for line in header_text.splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            length = int(headers.get("content-length") or "0")
            if method != "POST" or path != "/extra-data/xml":
                await self._send_response(writer, 404, {"ok": False, "error": "not_found"})
                return
            if length <= 0 or length > self._max_bytes:
                await self._send_response(writer, 413, {"ok": False, "error": "payload_too_large"})
                return
            body = await asyncio.wait_for(reader.readexactly(length), timeout=15)
            payload = json.loads(body.decode("utf-8"))
            auth = self._authorize(headers, payload)
            if auth is not None:
                await self._send_response(writer, auth[0], {"ok": False, "error": auth[1]})
                return
            result = await self.process_payload(payload)
            await self._send_response(writer, 200 if result.get("ok") else 500, result)
        except asyncio.TimeoutError:
            logger.warning("extra-data ingest request timed out while reading")
            try:
                await self._send_response(writer, 408, {"ok": False, "error": "request_timeout"})
            except Exception:
                pass
        except asyncio.LimitOverrunError:
            logger.warning("extra-data ingest request headers too large")
            try:
                await self._send_response(writer, 431, {"ok": False, "error": "headers_too_large"})
            except Exception:
                pass
        except asyncio.IncompleteReadError:
            logger.warning("extra-data ingest request ended before declared content-length")
            try:
                await self._send_response(writer, 400, {"ok": False, "error": "incomplete_request"})
            except Exception:
                pass
        except Exception as exc:
            logger.warning("extra-data ingest request failed: %s", exc)
            try:
                await self._send_response(writer, 500, {"ok": False, "error": str(exc)})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _send_response(self, writer: asyncio.StreamWriter, status: int, data: dict[str, Any]) -> None:
        reason = "OK" if status < 400 else "ERROR"
        raw = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode("ascii")
            + raw
        )
        await writer.drain()

    def _authorize(self, headers: dict[str, str], payload: dict[str, Any]) -> tuple[int, str] | None:
        if not self._token:
            if self._allow_unauth:
                return None
            return 503, "extra_token_not_configured"
        provided = (
            headers.get("x-agent-boot-extra-token")
            or str(payload.get("extra_data_token") or "")
        ).strip()
        if provided != self._token:
            return 401, "unauthorized"
        return None

    async def process_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        serial = str(payload.get("serial") or context.get("device_serial") or "")
        strategy = str(payload.get("strategy") or context.get("strategy") or "fb_posts")
        xml = str(payload.get("xml") or "")
        if not serial:
            return {"ok": False, "error": "serial_required"}
        if not xml or "<hierarchy" not in xml:
            return {"ok": False, "error": "invalid_xml"}
        expected_sha = str(payload.get("xml_sha256") or "")
        actual_sha = hashlib.sha256(xml.encode("utf-8")).hexdigest()
        if expected_sha and expected_sha != actual_sha:
            return {"ok": False, "error": "xml_sha256_mismatch"}

        async with self._lock_for_serial(serial):
            async with self._parse_sem:
                loop = asyncio.get_running_loop()
                parse_started = time.perf_counter()
                # Route XML parsing to the dedicated CPU pool when available.
                # Falls back to the default pool when the relay runtime is
                # not initialised (tests / standalone use).
                try:
                    from relay.runtime import cpu_executor as _cpu_exec
                    _parse_ex = _cpu_exec()
                except Exception:
                    _parse_ex = None
                items, diagnostic, snapshots = await loop.run_in_executor(
                    _parse_ex,
                    _parse_payload_items,
                    strategy,
                    xml,
                    context,
                    payload,
                )
                parse_ms = int((time.perf_counter() - parse_started) * 1000)

            if (
                strategy not in _SUPPORTED_CONTENT_STRATEGIES
                and strategy not in _SUPPORTED_ENTITY_STRATEGIES
                and strategy not in {
                "fb_comment_target",
                "fb_comment_target_tap",
                "fb_comment_filter_next",
                }
            ):
                return {"ok": False, "error": "unsupported_strategy", "strategy": strategy}

            if strategy in _SUPPORTED_ENTITY_STRATEGIES:
                if bool(context.get("persist", True)):
                    context = await self._writer.prepare_context_for_persist(context)
                    entity_write = await self._entity_writer.persist_items(
                        items,
                        context=context,
                        captured_at=payload.get("captured_at"),
                    )
                else:
                    entity_write = {
                        "attempted": 0,
                        "upserted": 0,
                        "observed": 0,
                        "discovered": 0,
                        "entity_ids": [],
                    }
                return {
                    "ok": True,
                    "serial": serial,
                    "strategy": strategy,
                    "parsed_count": len(items),
                    "inserted_attempted": entity_write["attempted"],
                    "inserted_count": entity_write["upserted"],
                    "duplicate_count": 0,
                    "entity_ids": entity_write.get("entity_ids") or [],
                    "observation_count": entity_write["observed"],
                    "discovery_count": entity_write["discovered"],
                    "diagnostic": diagnostic,
                    "xml_sha256": actual_sha,
                    "parse_ms": parse_ms,
                    "db_ms": int((time.perf_counter() - started) * 1000) - parse_ms,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    **({"items": items} if bool(context.get("return_items", True)) else {}),
                }

            should_persist = bool(context.get("persist", True)) and bool(context.get("collection"))
            if should_persist:
                try:
                    context = await self._writer.prepare_context_for_persist(context)
                except Exception as exc:
                    logger.warning(
                        "extra-data FK preflight failed; continuing without optional FK refs: %s",
                        exc,
                    )
                    for field in ("campaign_id", "execution_id", "user_id", "org_id"):
                        context.pop(field, None)

            content_type = str(context.get("content_type") or ("comment" if strategy.endswith("_comments") or strategy == "fb_comments" else "post"))
            item_level = int(context.get("item_level") if context.get("item_level") is not None else (1 if strategy.endswith("_comments") or strategy == "fb_comments" else 0))
            is_comment_strategy = strategy.endswith("_comments") or strategy == "fb_comments"
            if is_comment_strategy:
                context = _drop_stale_comment_parent_context(context, items, diagnostic)
            parent_id = context.get("parent_id") if is_comment_strategy else None
            parent_id_scoped = bool(context.get("parent_id_already_scoped"))
            if is_comment_strategy and not parent_id:
                from relay.extra_data.parent_resolve import resolve_fb_comment_parent_id

                parent_id, parent_id_scoped = resolve_fb_comment_parent_id(context, items)
            if is_comment_strategy and not parent_id and hasattr(
                self._writer, "lookup_parent_hash_for_post_pid"
            ):
                parent_id = await self._writer.lookup_parent_hash_for_post_pid(
                    collection=str(context.get("collection") or ""),
                    execution_id=context.get("execution_id") or context.get("hash_scope"),
                    parent_post_id=str(context.get("parent_post_id") or ""),
                    items=items,
                )
                parent_id_scoped = bool(parent_id)
            require_verified_parent = _requires_verified_comment_parent(context)
            has_verified_parent_context = _has_verified_comment_parent_context(context)
            if (
                is_comment_strategy
                and require_verified_parent
                and has_verified_parent_context
                and hasattr(self._writer, "lookup_parent_hash_for_post_pid")
            ):
                canonical_parent_id = await self._writer.lookup_parent_hash_for_post_pid(
                    collection=str(context.get("collection") or ""),
                    execution_id=context.get("execution_id") or context.get("hash_scope"),
                    parent_post_id=str(context.get("parent_post_id") or ""),
                    items=items,
                )
                if canonical_parent_id:
                    if parent_id and str(parent_id) != str(canonical_parent_id):
                        diagnostic["parent_context_relinked"] = True
                        diagnostic["context_parent_hash"] = str(parent_id)
                        diagnostic["canonical_parent_hash"] = str(canonical_parent_id)
                    parent_id = canonical_parent_id
                    parent_id_scoped = True
                    context["parent_id"] = canonical_parent_id
                    context["_active_comment_parent_hash"] = canonical_parent_id
                    context["parent_id_already_scoped"] = True
                else:
                    # PID relink missed (vivo often lands on comment sheet). Keep scoped
                    # parent hash from the fb_posts step in the same loop when verified.
                    if parent_id and parent_id_scoped:
                        diagnostic["parent_lookup_fallback"] = True
                    else:
                        diagnostic["parent_context_required"] = True
                        diagnostic["parent_post_row_missing"] = True
                        should_persist = False
                        parent_id = None
                        parent_id_scoped = False
            if (
                is_comment_strategy
                and require_verified_parent
                and not has_verified_parent_context
                and bool(context.get("allow_latest_post_parent_fallback"))
                and not parent_id
                and hasattr(self._writer, "lookup_latest_parent_hash_for_context")
            ):
                latest_parent_id = await self._writer.lookup_latest_parent_hash_for_context(
                    collection=str(context.get("collection") or ""),
                    execution_id=context.get("execution_id") or context.get("hash_scope"),
                    device_serial=context.get("device_serial") or serial,
                )
                if latest_parent_id:
                    parent_id = latest_parent_id
                    parent_id_scoped = True
                    context["parent_id"] = latest_parent_id
                    context["_active_comment_parent_hash"] = latest_parent_id
                    context["parent_id_already_scoped"] = True
                    context["parent_context_source"] = "latest_post_in_execution"
                    has_verified_parent_context = True
                    diagnostic["parent_context_latest_post_fallback"] = True
                    diagnostic["latest_parent_hash"] = str(latest_parent_id)
            if (
                is_comment_strategy
                and require_verified_parent
                and not has_verified_parent_context
            ):
                diagnostic["parent_context_required"] = True
                diagnostic["parent_context_missing"] = True
                should_persist = False
                parent_id = None
                parent_id_scoped = False
            if is_comment_strategy:
                items = _with_comment_parent_context(items, context, parent_id=parent_id)
            post_stats = _latest_post_stats(items) if is_comment_strategy else None
            if is_comment_strategy:
                diagnostic["post_stats_found"] = bool(post_stats)

            evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
            if not evidence and snapshots:
                evidence = {"hierarchy_xml": snapshots[-1]}

            from relay.extra_data.artifact_store import merge_evidence_into_item

            row_context = {
                **context,
                "device_serial": context.get("device_serial") or serial,
                "content_type": content_type,
                "parent_id_already_scoped": parent_id_scoped,
            }
            rows = [
                build_content_item_row(
                    merge_evidence_into_item(item, evidence),
                    row_context,
                    parent_id=parent_id,
                    item_level=item_level,
                    captured_at=payload.get("captured_at") or payload.get("captured_at_ms"),
                )
                for item in items
                if isinstance(item, dict) and item.get("_type") != "post_stats"
            ]
            row_items = [
                item
                for item in items
                if isinstance(item, dict) and item.get("_type") != "post_stats"
            ]
            if strategy == "fb_posts" and not row_items and context.get("open_post_detail"):
                synthetic_parent = _synthetic_post_from_opened_post(context)
                if synthetic_parent:
                    items.append(synthetic_parent)
                    row_context = {
                        **context,
                        "device_serial": context.get("device_serial") or serial,
                        "content_type": content_type,
                        "parent_id_already_scoped": parent_id_scoped,
                    }
                    rows = [
                        build_content_item_row(
                            merge_evidence_into_item(synthetic_parent, evidence),
                            row_context,
                            parent_id=parent_id,
                            item_level=item_level,
                            captured_at=payload.get("captured_at") or payload.get("captured_at_ms"),
                        )
                    ]
                    row_items = [synthetic_parent]
                    diagnostic["opened_post_synthetic_parent"] = True
            db_started = time.perf_counter()
            write = await self._insert_rows_with_retry(rows) if should_persist else {
                "attempted": 0,
                "inserted": 0,
                "duplicates": 0,
                "inserted_content_hashes": [],
            }
            parent_stats_updated = False
            if is_comment_strategy and post_stats:
                if not should_persist:
                    diagnostic["parent_stats_update_skipped_reason"] = "persist_disabled"
                elif not parent_id:
                    diagnostic["parent_stats_update_skipped_reason"] = "parent_missing"
                elif not hasattr(self._writer, "update_content_stats"):
                    diagnostic["parent_stats_update_skipped_reason"] = "writer_unsupported"
                else:
                    parent_stats_hash = (
                        str(parent_id)
                        if parent_id_scoped
                        else scope_content_hash(
                            str(parent_id),
                            context.get("hash_scope") or context.get("execution_id"),
                        )
                    )
                    try:
                        parent_stats_updated = bool(
                            await self._writer.update_content_stats(
                                content_hash=parent_stats_hash,
                                likes_count=post_stats.get("reactions"),
                                comments_count=post_stats.get("comments"),
                                shares_count=post_stats.get("shares"),
                            )
                        )
                        if parent_stats_updated:
                            diagnostic["post_stats_persisted"] = True
                        else:
                            diagnostic["parent_stats_update_skipped_reason"] = "parent_not_found"
                    except Exception as exc:
                        diagnostic["parent_stats_update_skipped_reason"] = "update_failed"
                        logger.warning("extra-data parent stats update failed: %s", exc)
            elif is_comment_strategy and should_persist:
                diagnostic["parent_stats_update_skipped_reason"] = "post_stats_missing"
            db_ms = int((time.perf_counter() - db_started) * 1000)

        payload_xml_bytes = sum(len(snapshot.encode("utf-8")) for snapshot in snapshots)
        try:
            xml_bytes = int(diagnostic.get("xml_bytes", payload_xml_bytes))
        except (TypeError, ValueError):
            xml_bytes = payload_xml_bytes
        try:
            snapshot_count = int(diagnostic.get("snapshot_count", len(snapshots)))
        except (TypeError, ValueError):
            snapshot_count = len(snapshots)

        result = {
            "ok": True,
            "serial": serial,
            "strategy": strategy,
            "parsed_count": len(items),
            "inserted_attempted": write.get("attempted", 0),
            "inserted_count": write.get("inserted", 0),
            "duplicate_count": write.get("duplicates", 0),
            "inserted_content_hashes": write.get("inserted_content_hashes") or [],
            "batch_content_hashes": [str(r["content_hash"]) for r in rows if r.get("content_hash")],
            "diagnostic": diagnostic,
            "xml_bytes": xml_bytes,
            "snapshot_count": snapshot_count,
            "xml_sha256": actual_sha,
            "parse_ms": parse_ms,
            "db_ms": db_ms,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        if payload_xml_bytes != xml_bytes:
            result["payload_xml_bytes"] = payload_xml_bytes
        if len(snapshots) != snapshot_count:
            result["payload_snapshot_count"] = len(snapshots)
        if bool(context.get("return_items", False)):
            result["items"] = [
                item
                for item in items
                if isinstance(item, dict) and item.get("_type") != "post_stats"
            ]
        evidence_payload = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        screenshot_b64 = evidence_payload.get("screenshot_b64")
        if isinstance(screenshot_b64, str) and screenshot_b64.strip() and should_persist:
            result["screenshot_b64"] = screenshot_b64.strip()
        if strategy == "fb_posts" and items:
            post_id_map = _build_post_id_map(items, context)
            if post_id_map:
                result["post_id_map"] = post_id_map
            active_parent = _active_parent_from_opened_post(context, row_items, rows)
            if active_parent is None and context.get("open_post_detail") and row_items and rows:
                active_parent = _active_parent_post_payload(row_items[0], rows[0])
                if active_parent:
                    active_parent["selection_reason"] = "post_detail_first_parsed"
            if active_parent is None and len(row_items) == 1 and len(rows) == 1:
                active_parent = _active_parent_post_payload(row_items[0], rows[0])
            if active_parent:
                if context.get("open_post_detail"):
                    active_parent.setdefault("source", "post_detail")
                result["active_parent_post"] = active_parent
        return result

    async def _insert_rows_with_retry(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        attempts = max(1, int(os.getenv("AGENT_BOOT_CONTENT_DB_RETRIES", "3")))
        base_delay = max(0.01, float(os.getenv("AGENT_BOOT_CONTENT_DB_RETRY_BASE_DELAY", "0.2")))
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._writer.insert_rows(rows)
            except Exception as exc:
                last_exc = exc
                if ContentItemWriter._is_content_items_fk_violation(exc):
                    stripped = ContentItemWriter._strip_optional_fk_fields(rows)
                    logger.warning(
                        "content_items optional FK failed at ingest layer (%s); retrying without %s",
                        exc,
                        ", ".join(stripped) or "optional FK refs",
                    )
                    try:
                        return await self._writer.insert_rows(rows)
                    except Exception as retry_exc:
                        last_exc = retry_exc
                        if not ContentItemWriter._is_content_items_fk_violation(retry_exc):
                            raise
                if attempt >= attempts - 1:
                    break
                delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay)
                logger.warning("content_items insert failed, retrying in %.2fs: %s", delay, exc)
                await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc
