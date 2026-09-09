"""Contract for the platform parser seam (`BasePlatformParser.extract`).

A4 moved Facebook out of the `_parse_items` if-chain and into the same registry
every other platform uses. The bar is that nothing observable changed: for each
entity, `_parse_items` must return exactly what calling the Facebook pipeline
directly returns — on the same XML string, byte for byte. Expectations here are
never hand-written; they are read off the pipeline itself.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from relay.extra_data.ingest import _parse_items
from relay.extra_data.parsers.facebook.adapter import FacebookParser
from relay.extra_data.parsers.platform_detector import (
    detect_parser,
    list_supported_platforms,
    parser_for_platform,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FEED_XML = (FIXTURES / "facebook" / "codex_vn_two_post_feed.xml").read_text(
    encoding="utf-8"
)
SHEET_XML = (FIXTURES / "vivo_comment_sheet_kent_juno_post.xml").read_text(
    encoding="utf-8"
)
GROUPS_XML = (
    '<hierarchy><node clickable="true" '
    'content-desc="OpenClaw VN, Nhóm Công khai · 100 thành viên" />'
    "</hierarchy>"
)
PAGES_XML = (
    '<hierarchy><node clickable="true" '
    'content-desc="Go2Joy Vietnam, Trang · 120K người thích · 130K người theo dõi" />'
    "</hierarchy>"
)


# ─── Every entity matches the pipeline it wraps ─────────────────────────────


def _stable(result: tuple[list, dict]) -> tuple[list, dict]:
    """Drop `elapsed_ms`: it is wall-clock, so two runs never compare equal."""
    items, diagnostic = result
    return items, {k: v for k, v in diagnostic.items() if k != "elapsed_ms"}


def test_fb_posts_matches_pipeline() -> None:
    from relay.extra_data.parsers.facebook import parse_fb_posts_from_xml_with_diagnostic

    context = {"source_index": 3}
    assert _stable(_parse_items("fb_posts", FEED_XML, context)) == _stable(
        parse_fb_posts_from_xml_with_diagnostic(FEED_XML, source_index=3)
    )


def test_fb_comments_matches_pipeline() -> None:
    from relay.extra_data.parsers.facebook import parse_fb_comments_from_xml_with_diagnostic

    context = {"parent_post_id": "parent-hash", "max_items": 25}
    assert _stable(_parse_items("fb_comments", SHEET_XML, context)) == _stable(
        parse_fb_comments_from_xml_with_diagnostic(
            SHEET_XML, parent_post_id="parent-hash", max_items=25
        )
    )


def test_fb_groups_matches_pipeline() -> None:
    from relay.extra_data.parsers.facebook.group_pipeline import parse_group_search_results

    assert _parse_items("fb_groups", GROUPS_XML, {}) == parse_group_search_results(
        GROUPS_XML
    )


def test_fb_pages_matches_pipeline() -> None:
    from relay.extra_data.parsers.facebook.page_pipeline import parse_page_search_results

    assert _parse_items("fb_pages", PAGES_XML, {}) == parse_page_search_results(
        PAGES_XML
    )


def test_fb_comment_filter_next_matches_pipeline() -> None:
    from relay.extra_data.parsers.facebook.comment_filter import (
        resolve_comment_filter_next_tap,
    )

    context = {"comment_filter": "all_comments"}
    items, diagnostic = _parse_items("fb_comment_filter_next", SHEET_XML, context)
    assert items == []
    assert diagnostic == resolve_comment_filter_next_tap(SHEET_XML, context)


def test_fb_comment_target_matches_resolver() -> None:
    from relay.extra_data.parsers.facebook import resolve_comment_targets_from_xml

    top, ranked = resolve_comment_targets_from_xml(
        FEED_XML, locked_anchor=None, exclude_post_anchors=[]
    )
    assert top, "fixture must offer at least one comment target"

    items, diagnostic = _parse_items("fb_comment_target", FEED_XML, {})
    assert items == []
    assert diagnostic["reason_code"] == "ok"
    assert diagnostic["candidate_count"] == len(ranked)
    assert diagnostic["target"]["bounds"] == list(top["comment_bounds"])
    assert len(diagnostic["alternates"]) == len(ranked) - 1


def test_fb_comment_target_tap_is_the_same_entity() -> None:
    assert _parse_items("fb_comment_target_tap", FEED_XML, {}) == _parse_items(
        "fb_comment_target", FEED_XML, {}
    )


# ─── The XML reaches the pipeline unchanged ─────────────────────────────────


def test_pipeline_receives_the_exact_xml_string(monkeypatch) -> None:
    """No re-serialisation through lxml: folding labels depends on the spacing
    the device actually sent (docs/adr-facebook-ui-reasoning.md)."""
    seen: dict[str, Any] = {}

    class Module:
        pass

    module = Module()

    def fake_parse(xml, source_index=0):
        seen["xml"] = xml
        return [], {"reason_code": "ok"}

    module.parse_fb_posts_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    _parse_items("fb_posts", FEED_XML, {})
    assert seen["xml"] is FEED_XML


# ─── Registry ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "package",
    ["com.facebook.katana", "com.facebook.lite", "com.facebook.orca"],
)
def test_facebook_packages_resolve_to_facebook_parser(package: str) -> None:
    parser = detect_parser(package)
    assert isinstance(parser, FacebookParser)
    assert list_supported_platforms()[package] == "facebook"


def test_parser_for_platform_covers_every_declared_platform() -> None:
    for platform in ("facebook", "instagram", "tiktok", "linkedin"):
        assert parser_for_platform(platform) is not None
    assert parser_for_platform("myspace") is None


# ─── auto_* resolves Facebook through the registry ──────────────────────────


def test_auto_posts_uses_package_name() -> None:
    assert _stable(
        _parse_items("auto_posts", FEED_XML, {"package_name": "com.facebook.katana"})
    ) == _stable(_parse_items("fb_posts", FEED_XML, {}))


def test_auto_posts_falls_back_to_hierarchy() -> None:
    assert _stable(_parse_items("auto_posts", FEED_XML, {})) == _stable(
        _parse_items("fb_posts", FEED_XML, {})
    )


def test_auto_posts_without_any_signal_reports_no_parser() -> None:
    items, diagnostic = _parse_items("auto_posts", "<hierarchy />", {})
    assert items == []
    assert diagnostic["reason_code"] == "platform_parser_not_found"


# ─── Stubs keep working, and can now say "I don't do that" ──────────────────


def test_tiktok_stub_still_parses_through_the_seam() -> None:
    items, diagnostic = _parse_items("tiktok_posts", "<hierarchy />", {})
    assert items == []
    assert diagnostic == {
        "reason_code": "ok",
        "platform": "tiktok",
        "items_returned": 0,
    }


@pytest.mark.parametrize("strategy", ["fb_reels", "tiktok_reels"])
def test_unknown_entity_reports_not_implemented(strategy: str) -> None:
    items, diagnostic = _parse_items(strategy, "<hierarchy />", {})
    assert items == []
    assert diagnostic["reason_code"] == "not_implemented"
    assert diagnostic["entity"] == "reels"
