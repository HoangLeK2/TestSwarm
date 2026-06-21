"""Tests for FB comment button bounds resolution (label → clickable ancestor)."""

from __future__ import annotations

from lxml import etree

from relay.extra_data.parsers.facebook.comment_pipeline import (
    _comment_button_within_post_card,
    _find_binh_luan_button_bounds_in_element,
    _resolve_comment_button_bounds,
)


def _card_xml() -> etree._Element:
    xml = """
    <node bounds="[0,900][1080,1500]">
      <node class="android.view.ViewGroup" clickable="true" bounds="[40,1380][200,1440]">
        <node class="android.widget.TextView" text="Bình luận" clickable="false"
              bounds="[50,1390][150,1420]" />
      </node>
    </node>
    """
    return etree.fromstring(xml)


def test_resolve_promotes_clickable_ancestor_for_static_label() -> None:
    card = _card_xml()
    label = card.find('.//node[@text="Bình luận"]')
    assert label is not None
    resolved = _resolve_comment_button_bounds(label)
    assert resolved is not None
    bnds, is_btn = resolved
    assert bnds == (40, 1380, 200, 1440)
    assert is_btn is False


def test_find_bounds_in_card_uses_ancestor_not_label() -> None:
    card = _card_xml()
    bnds = _find_binh_luan_button_bounds_in_element(card)
    assert bnds == (40, 1380, 200, 1440)


def test_rejects_button_below_post_card() -> None:
    btn = (0, 2100, 120, 2140)
    card = (0, 900, 1080, 1500)
    assert not _comment_button_within_post_card(btn, card)


def test_like_button_a11y_does_not_match_comment_token() -> None:
    from lxml import etree

    from relay.extra_data.parsers.facebook.comment_pipeline import _node_has_comment_button_token

    like = etree.fromstring(
        '<node class="android.widget.Button" clickable="true" '
        'content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." '
        'bounds="[40,1100][200,1160]" />'
    )
    comment = etree.fromstring(
        '<node class="android.widget.Button" clickable="true" text="Bình luận" '
        'bounds="[220,1100][380,1160]" />'
    )
    assert not _node_has_comment_button_token(like)
    assert _node_has_comment_button_token(comment)


def test_action_bar_finds_comment_not_like() -> None:
    xml = """
    <node bounds="[0,900][1080,1500]">
      <node class="android.widget.Button" clickable="true"
            content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận."
            bounds="[40,1100][200,1160]" />
      <node class="android.widget.Button" clickable="true" text="Bình luận"
            bounds="[220,1100][380,1160]" />
      <node class="android.widget.Button" clickable="true"
            content-desc="Nút Chia sẻ. Nhấn đúp để chia sẻ bài viết."
            bounds="[400,1100][560,1160]" />
    </node>
    """
    card = etree.fromstring(xml)
    bnds = _find_binh_luan_button_bounds_in_element(card)
    assert bnds == (220, 1100, 380, 1160)


def test_click_target_includes_u2_xpath_from_node() -> None:
    from relay.extra_data.parsers.facebook.comment_pipeline import (
        _find_comment_button_click_target_in_element,
    )

    xml = """
    <node bounds="[0,900][1080,1500]">
      <node class="android.widget.Button" clickable="true" text="Bình luận"
            bounds="[220,1100][380,1160]" />
    </node>
    """
    card = etree.fromstring(xml)
    hit = _find_comment_button_click_target_in_element(card)
    assert hit is not None
    u2 = hit["u2_click"]
    assert '[220,1100][380,1160]' in u2["xpath"]
    assert u2["selector"]["text"] == "Bình luận"


def test_nut_binh_luan_content_desc_matches_action_button() -> None:
    from lxml import etree

    from relay.extra_data.parsers.facebook.comment_pipeline import _node_has_comment_button_token

    node = etree.fromstring(
        '<node class="android.widget.Button" clickable="true" '
        'content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." bounds="[203,2649][433,2800]" />'
    )
    assert _node_has_comment_button_token(node)


def test_reply_and_comment_like_do_not_match_comment_button_token() -> None:
    from lxml import etree

    from relay.extra_data.parsers.facebook.comment_pipeline import _node_has_comment_button_token

    reply = etree.fromstring(
        '<node class="android.widget.Button" clickable="true" text="Trả lời" bounds="[120,1350][220,1390]" />'
    )
    comment_like = etree.fromstring(
        '<node class="android.widget.Button" clickable="true" '
        'content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." '
        'bounds="[40,1350][160,1390]" />'
    )
    assert not _node_has_comment_button_token(reply)
    assert not _node_has_comment_button_token(comment_like)


def test_post_detail_prefers_action_bar_comment_over_inline_preview(monkeypatch) -> None:
    from lxml import etree

    from relay.extra_data.parsers.facebook.comment_pipeline import (
        _find_comment_button_click_target_in_element,
        _post_action_bar_row_band,
        _resolve_post_detail_comment_target,
    )
    from relay.extra_data.parsers.facebook import post_open_pipeline as pop_mod

    xml = """
    <hierarchy bounds="[0,0][1080,2400]">
      <node class="android.widget.Button" clickable="true"
            content-desc="Nút Thích. Nhấn đúp để bày tỏ cảm xúc về bài viết."
            bounds="[40,1180][200,1240]" />
      <node class="android.widget.Button" clickable="true" text="Bình luận"
            bounds="[220,1180][380,1240]" />
      <node class="android.widget.Button" clickable="true"
            content-desc="Nút Chia sẻ. Nhấn đúp để chia sẻ bài viết."
            bounds="[400,1180][560,1240]" />
      <node class="android.view.ViewGroup" clickable="true" bounds="[0,1260][1080,1700]">
        <node class="android.widget.Button" clickable="true"
              content-desc="55 bình luận" bounds="[40,1280][220,1320]" />
        <node class="android.widget.Button" clickable="true" text="Thích"
              bounds="[40,1360][120,1400]" />
        <node class="android.widget.Button" clickable="true" text="Trả lời"
              bounds="[140,1360][240,1400]" />
        <node class="android.widget.TextView" text="Kim Ssa" bounds="[80,1330][260,1360]" />
      </node>
    </hierarchy>
    """
    root = etree.fromstring(xml)
    band = _post_action_bar_row_band(root, 2400)
    assert band is not None
    hit = _find_comment_button_click_target_in_element(
        root,
        y_band=band,
        prefer_compact=True,
        max_tap_height=120,
    )
    assert hit is not None
    assert list(hit["bounds"]) == [220, 1180, 380, 1240]

    monkeypatch.setattr(pop_mod, "hierarchy_is_fb_post_detail_from_xml", lambda _xml: True)
    cand = _resolve_post_detail_comment_target(
        root,
        locked_anchor={"pid": "p1", "post_key": "p1"},
        screen_h=2400,
        screen_w=1080,
    )
    assert cand is not None
    assert list(cand["comment_bounds"]) == [220, 1180, 380, 1240]


def test_compact_target_avoids_large_clickable_wrapper() -> None:
    from lxml import etree

    from relay.extra_data.parsers.facebook.comment_pipeline import (
        _find_comment_button_click_target_in_element,
    )

    xml = """
    <node bounds="[0,0][1080,2400]">
      <node class="android.view.ViewGroup" clickable="true" bounds="[0,1150][1080,1700]">
        <node class="android.widget.Button" clickable="true" text="Bình luận"
              bounds="[220,1180][380,1220]" />
        <node class="android.widget.TextView" text="Kim Ssa" bounds="[80,1300][300,1330]" />
      </node>
    </node>
    """
    root = etree.fromstring(xml)
    hit = _find_comment_button_click_target_in_element(
        root,
        prefer_compact=True,
        max_tap_height=120,
    )
    assert hit is not None
    assert list(hit["bounds"]) == [220, 1180, 380, 1220]
