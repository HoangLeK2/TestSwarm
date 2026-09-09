"""Facebook parser wired into the platform registry.

Thin adapter only: every branch below is the Facebook pipeline call that used to
live inline in `relay/extra_data/ingest.py::_parse_items`. The pipeline receives
the raw XML *string* — it parses and normalises UI spacing itself, and
re-serialising an lxml tree would change what the label folder sees
(`docs/adr-facebook-ui-reasoning.md`).

Pipeline imports stay inside the methods so the registry can import this module
without pulling the Facebook extraction stack in at startup.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from relay.extra_data.parsers.base import BasePlatformParser

Result = Tuple[List[dict], Dict[str, Any]]


class FacebookParser(BasePlatformParser):
    platform = "facebook"
    package_names = [
        "com.facebook.katana",
        "com.facebook.lite",
        "com.facebook.orca",  # Messenger — same hierarchy patterns for posts
    ]

    def extract(self, entity: str, xml: str, context: Dict[str, Any]) -> Result:
        handler: Callable[[str, Dict[str, Any]], Result] | None = {
            "posts": self._posts,
            "comments": self._comments,
            "groups": self._groups,
            "pages": self._pages,
            "comment_target": self._comment_target,
            "comment_target_tap": self._comment_target,
            "comment_filter_next": self._comment_filter_next,
        }.get(entity)
        if handler is None:
            return [], {
                "reason_code": "not_implemented",
                "entity": entity,
                "platform": self.platform,
            }
        return handler(xml, context or {})

    # ─── Entities ──────────────────────────────────────────────────────

    def _posts(self, xml: str, context: Dict[str, Any]) -> Result:
        from relay.extra_data.parsers.facebook import parse_fb_posts_from_xml_with_diagnostic

        return parse_fb_posts_from_xml_with_diagnostic(
            xml,
            source_index=int(context.get("source_index") or 0),
        )

    def _comments(self, xml: str, context: Dict[str, Any]) -> Result:
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

    def _groups(self, xml: str, context: Dict[str, Any]) -> Result:
        from relay.extra_data.parsers.facebook.group_pipeline import (
            parse_group_search_results,
        )

        return parse_group_search_results(xml)

    def _pages(self, xml: str, context: Dict[str, Any]) -> Result:
        from relay.extra_data.parsers.facebook.page_pipeline import (
            parse_page_search_results,
        )

        return parse_page_search_results(xml)

    def _comment_filter_next(self, xml: str, context: Dict[str, Any]) -> Result:
        from relay.extra_data.parsers.facebook.comment_filter import (
            resolve_comment_filter_next_tap,
        )

        return [], resolve_comment_filter_next_tap(xml, context)

    def _comment_target(self, xml: str, context: Dict[str, Any]) -> Result:
        from relay.extra_data.parsers.facebook import resolve_comment_targets_from_xml
        from relay.extra_data.parsers.facebook.comment_pipeline import (
            diagnose_comment_target_resolution,
        )
        from relay.extra_data.parsers.facebook.parser import (
            _hierarchy_is_fb_comment_sheet,
            _parse_xml,
        )
        from relay.extra_data.writer import compute_content_hash, scope_content_hash

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
        # Posts already commented on in this run, so a feed loop cannot tap the
        # same card again once it scrolls back past it.
        exclude_anchors = context.get("comment_exclude_anchors")
        if not isinstance(exclude_anchors, list):
            exclude_anchors = []
        top, ranked = resolve_comment_targets_from_xml(
            xml,
            locked_anchor=locked_anchor,
            exclude_post_anchors=exclude_anchors,
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
            or context.get("_posts_dedupe_field")
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
