"""Resolver-level tests for ``resolve_comment_targets_from_xml``.

These tests exercise the pure pieces of the comment-target ranking logic
(filtering, scoring, tie-breaking) without building a full Facebook feed XML
— a job that is covered by the integration / capture-replay tests.
"""

from __future__ import annotations

from pathlib import Path

from relay.extra_data.parsers.facebook import comment_pipeline


SCREEN_H = 2200
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "facebook"


def _cand(
    *,
    comment_bounds,
    parent_post_bounds=None,
    post=None,
):
    return {
        "comment_bounds": comment_bounds,
        "parent_post_bounds": parent_post_bounds,
        "post": post or {"_pid": "p", "post_key": "p"},
        "feed_item_index": 0,
    }


def test_filter_drops_button_above_top_band() -> None:
    cand = _cand(comment_bounds=(0, int(SCREEN_H * 0.05), 100, int(SCREEN_H * 0.10)))
    assert not comment_pipeline._comment_candidate_passes_filter(cand, screen_h=SCREEN_H)


def test_filter_drops_button_below_bottom_band() -> None:
    cand = _cand(comment_bounds=(0, int(SCREEN_H * 0.985), 100, int(SCREEN_H * 0.995)))
    assert not comment_pipeline._comment_candidate_passes_filter(cand, screen_h=SCREEN_H)


def test_filter_keeps_low_action_bar_on_tall_screen() -> None:
    # Vivo group feed: action bar can sit at y≈2649 on 2800px screen.
    cand = _cand(comment_bounds=(203, 2649, 433, 2800))
    assert comment_pipeline._comment_candidate_passes_filter(cand, screen_h=2800)


def test_filter_keeps_button_inside_band() -> None:
    cand = _cand(comment_bounds=(0, int(SCREEN_H * 0.45), 100, int(SCREEN_H * 0.55)))
    assert comment_pipeline._comment_candidate_passes_filter(cand, screen_h=SCREEN_H)


def test_filter_rejects_zero_size_bounds() -> None:
    cand = _cand(comment_bounds=(50, 1100, 50, 1100))
    assert not comment_pipeline._comment_candidate_passes_filter(cand, screen_h=SCREEN_H)


def test_score_prefers_center_aligned_card() -> None:
    near_center = _cand(
        comment_bounds=(0, 1080, 100, 1120),
        parent_post_bounds=(0, 900, 1080, 1300),
        post={"_pid": "p1", "post_key": "p1", "timestamp": "1h"},
    )
    far_off = _cand(
        comment_bounds=(0, 1900, 100, 1940),
        parent_post_bounds=(0, 1750, 1080, 1960),
        post={"_pid": "p2", "post_key": "p2", "timestamp": "1h"},
    )
    s_near = comment_pipeline._score_comment_candidate(near_center, screen_h=SCREEN_H, center_y_ratio=0.5)["score"]
    s_far = comment_pipeline._score_comment_candidate(far_off, screen_h=SCREEN_H, center_y_ratio=0.5)["score"]
    assert s_near < s_far


def test_score_penalises_missing_strong_key() -> None:
    with_key = _cand(
        comment_bounds=(0, 1080, 100, 1120),
        parent_post_bounds=(0, 900, 1080, 1300),
        post={"_pid": "p1", "post_key": "p1", "timestamp": "1h"},
    )
    no_key = _cand(
        comment_bounds=(0, 1080, 100, 1120),
        parent_post_bounds=(0, 900, 1080, 1300),
        post={"_pid": "p2", "timestamp": "1h"},
    )
    s_with = comment_pipeline._score_comment_candidate(with_key, screen_h=SCREEN_H, center_y_ratio=0.5)["score"]
    s_without = comment_pipeline._score_comment_candidate(no_key, screen_h=SCREEN_H, center_y_ratio=0.5)["score"]
    assert s_without > s_with


def test_score_penalises_bottom_edge_buttons() -> None:
    center_button = _cand(
        comment_bounds=(0, 1080, 100, 1120),
        parent_post_bounds=(0, 1000, 1080, 1300),
        post={"_pid": "a", "post_key": "a", "timestamp": "1h"},
    )
    bottom_button = _cand(
        comment_bounds=(0, int(SCREEN_H * 0.86), 100, int(SCREEN_H * 0.90)),
        parent_post_bounds=(0, int(SCREEN_H * 0.70), 1080, int(SCREEN_H * 0.90)),
        post={"_pid": "b", "post_key": "b", "timestamp": "1h"},
    )
    s_center = comment_pipeline._score_comment_candidate(center_button, screen_h=SCREEN_H, center_y_ratio=0.5)
    s_bottom = comment_pipeline._score_comment_candidate(bottom_button, screen_h=SCREEN_H, center_y_ratio=0.5)
    assert s_bottom["breakdown"]["bottom_risk_penalty"] > 0
    assert s_bottom["score"] > s_center["score"]


def test_score_penalises_partially_offscreen_card() -> None:
    fully_visible = _cand(
        comment_bounds=(0, 1080, 100, 1120),
        parent_post_bounds=(0, 1000, 1080, 1500),
        post={"_pid": "a", "post_key": "a", "timestamp": "1h"},
    )
    cut_off = _cand(
        comment_bounds=(0, 1080, 100, 1120),
        parent_post_bounds=(0, -200, 1080, 1500),
        post={"_pid": "b", "post_key": "b", "timestamp": "1h"},
    )
    s_visible = comment_pipeline._score_comment_candidate(fully_visible, screen_h=SCREEN_H, center_y_ratio=0.5)
    s_cut = comment_pipeline._score_comment_candidate(cut_off, screen_h=SCREEN_H, center_y_ratio=0.5)
    assert s_cut["breakdown"]["cut_penalty"] > 0
    assert s_cut["score"] > s_visible["score"]


def test_resolve_picks_center_post_when_three_visible(monkeypatch) -> None:
    """End-to-end: top/middle/bottom posts → middle wins (the user's bug)."""

    synthetic = [
        _cand(
            comment_bounds=(40, 380, 200, 440),
            parent_post_bounds=(0, 220, 1080, 720),
            post={"_pid": "top", "post_key": "top", "text": "top", "author": "A", "timestamp": "5h"},
        ),
        _cand(
            comment_bounds=(40, 1080, 200, 1140),
            parent_post_bounds=(0, 900, 1080, 1480),
            post={"_pid": "mid", "post_key": "mid", "text": "middle", "author": "B", "timestamp": "1h"},
        ),
        _cand(
            comment_bounds=(40, 1740, 200, 1800),
            parent_post_bounds=(0, 1600, 1080, 1900),
            post={"_pid": "bot", "post_key": "bot", "text": "bottom", "author": "C", "timestamp": "10m"},
        ),
    ]

    def fake_builder(element, *, feed_item_index):
        if feed_item_index < len(synthetic):
            cand = dict(synthetic[feed_item_index])
            cand["feed_item_index"] = feed_item_index
            return cand
        return None

    def fake_pick(_containers, _root):
        class FakeFeed:
            def findall(self, _tag):
                return list(range(len(synthetic)))

        return FakeFeed()

    class FakeRoot:
        def xpath(self, _expr):
            return [object()]

    monkeypatch.setattr(comment_pipeline, "_build_comment_candidate", fake_builder)
    from relay.extra_data.parsers.facebook import parser as parser_mod
    monkeypatch.setattr(parser_mod, "_parse_xml", lambda _xml: FakeRoot())
    monkeypatch.setattr(parser_mod, "_infer_screen_size", lambda _root: (1080, SCREEN_H))
    monkeypatch.setattr(parser_mod, "_pick_feed_container", fake_pick)
    from relay.extra_data.parsers.facebook import feed_pipeline as feed_mod
    monkeypatch.setattr(feed_mod, "_is_ad_container", lambda _e: False)
    from relay.extra_data.parsers.facebook import post_open_pipeline as pop_mod
    monkeypatch.setattr(pop_mod, "hierarchy_is_fb_post_detail_from_xml", lambda _xml: False)

    top, ranked = comment_pipeline.resolve_comment_targets_from_xml("<hierarchy />")
    assert top is not None
    assert top["post"]["post_key"] == "mid"
    keys = [c["post"]["post_key"] for c in ranked]
    assert keys[0] == "mid"
    assert set(keys) == {"mid", "top", "bot"}


def test_resolve_tie_break_prefers_strong_key(monkeypatch) -> None:
    """Two posts with the same score: the one with a stable id wins."""

    weak = _cand(
        comment_bounds=(40, 1080, 200, 1140),
        parent_post_bounds=(0, 900, 1080, 1300),
        post={"_pid": "weak", "text": "weak", "author": "X"},
    )
    strong = _cand(
        comment_bounds=(40, 1080, 200, 1140),
        parent_post_bounds=(0, 900, 1080, 1300),
        post={"_pid": "strong", "post_key": "strong", "text": "strong", "author": "Y", "timestamp": "1h"},
    )

    def fake_builder(element, *, feed_item_index):
        return [weak, strong][feed_item_index]

    def fake_pick(_containers, _root):
        class FakeFeed:
            def findall(self, _tag):
                return [object(), object()]

        return FakeFeed()

    class FakeRoot:
        def xpath(self, _expr):
            return [object()]

    monkeypatch.setattr(comment_pipeline, "_build_comment_candidate", fake_builder)
    from relay.extra_data.parsers.facebook import parser as parser_mod
    monkeypatch.setattr(parser_mod, "_parse_xml", lambda _xml: FakeRoot())
    monkeypatch.setattr(parser_mod, "_infer_screen_size", lambda _root: (1080, SCREEN_H))
    monkeypatch.setattr(parser_mod, "_pick_feed_container", fake_pick)
    from relay.extra_data.parsers.facebook import feed_pipeline as feed_mod
    monkeypatch.setattr(feed_mod, "_is_ad_container", lambda _e: False)
    from relay.extra_data.parsers.facebook import post_open_pipeline as pop_mod
    monkeypatch.setattr(pop_mod, "hierarchy_is_fb_post_detail_from_xml", lambda _xml: False)

    top, ranked = comment_pipeline.resolve_comment_targets_from_xml("<hierarchy />")
    assert top is not None
    assert top["post"]["post_key"] == "strong"
    assert ranked[1]["post"]["_pid"] == "weak"


def test_locked_anchor_prefers_matching_candidate() -> None:
    mid = _cand(
        comment_bounds=(40, int(SCREEN_H * 0.50), 200, int(SCREEN_H * 0.56)),
        parent_post_bounds=(0, int(SCREEN_H * 0.35), 1080, int(SCREEN_H * 0.62)),
        post={"_pid": "mid", "post_key": "mid", "author": "Alice", "text": "middle post"},
    )
    other = _cand(
        comment_bounds=(40, int(SCREEN_H * 0.48), 200, int(SCREEN_H * 0.54)),
        parent_post_bounds=(0, int(SCREEN_H * 0.33), 1080, int(SCREEN_H * 0.60)),
        post={"_pid": "other", "post_key": "other", "author": "Bob", "text": "other post"},
    )
    for cand in (mid, other):
        cand.update(
            comment_pipeline._score_comment_candidate(
                cand,
                screen_h=SCREEN_H,
                screen_w=1080,
                center_y_ratio=0.5,
            )
        )
    comment_pipeline._apply_locked_anchor_scoring(
        other,
        {"post_key": "other", "author": "Bob", "text_prefix": "other post"},
    )
    comment_pipeline._apply_locked_anchor_scoring(
        mid,
        {"post_key": "other", "author": "Bob", "text_prefix": "other post"},
    )
    assert float(other["score"]) < float(mid["score"])


def test_legacy_center_wrapper_returns_post_and_bounds(monkeypatch) -> None:
    one = _cand(
        comment_bounds=(40, 1080, 200, 1140),
        parent_post_bounds=(0, 900, 1080, 1300),
        post={"_pid": "only", "post_key": "only"},
    )
    monkeypatch.setattr(
        comment_pipeline,
        "resolve_comment_targets_from_xml",
        lambda _xml, **_: (one, [one]),
    )
    post, bounds = comment_pipeline.resolve_center_comment_target_from_xml("<hierarchy />")
    assert post == one["post"]
    assert bounds == one["comment_bounds"]


def test_legacy_center_wrapper_returns_none_when_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        comment_pipeline,
        "resolve_comment_targets_from_xml",
        lambda _xml, **_: (None, []),
    )
    post, bounds = comment_pipeline.resolve_center_comment_target_from_xml("<hierarchy />")
    assert post is None and bounds is None


def test_profile_post_static_comment_label_resolves_target() -> None:
    xml = (FIXTURES / "mtp_profile_coauthor_pinned.xml").read_text(encoding="utf-8")

    top, ranked = comment_pipeline.resolve_comment_targets_from_xml(xml)

    assert top is not None
    assert top["comment_bounds"] == (284, 2032, 585, 2186)
    assert top["post"]["author"] == "M-TP"
    assert ranked
