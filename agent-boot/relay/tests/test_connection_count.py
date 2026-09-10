"""Reading how many friends an account actually has.

This number decides which playbook an account runs and is the only way to tell
whether any of the friend-growing work is working. Sending is easy to observe;
growing is not.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import relay.u2_executor as u2_exec_mod

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "facebook"


def _labels_xml(*labels: str) -> str:
    nodes = "".join(
        f'<node text="{label}" content-desc="" bounds="[0,0][100,50]" />'
        for label in labels
    )
    return f"<hierarchy>{nodes}</hierarchy>"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("0 bạn bè", 0),
        ("12 bạn bè", 12),
        # Vietnamese groups thousands with "."; English with ",".
        ("1.234 bạn bè", 1234),
        ("1,234 friends", 1234),
        # Abbreviated counts put the decimal mark where the other format puts
        # the group separator, so both readings must land on 1200.
        ("1,2K bạn bè", 1200),
        ("1.2K friends", 1200),
        ("567 friends", 567),
    ],
)
def test_reads_every_count_format_facebook_emits(label: str, expected: int) -> None:
    assert u2_exec_mod._fb_read_count(_labels_xml(label))["value"] == expected


def test_ignores_labels_that_only_mention_friends() -> None:
    result = u2_exec_mod._fb_read_count(_labels_xml("Xem tất cả bạn bè"))
    assert result["found"] is False
    assert result["reason"] == "count_not_visible"


def test_prefers_the_account_total_over_a_row_count() -> None:
    """A profile also shows mutual counts inside suggestion rows."""
    result = u2_exec_mod._fb_read_count(
        _labels_xml("Nguyen Van A", "3 bạn chung", "248 bạn bè")
    )
    assert result["value"] == 248


def test_empty_friend_list_reads_as_zero_not_as_unknown() -> None:
    """Captured from a real cold account (Android 16, Facebook 2026-08).

    Facebook renders no number at all when the list is empty — it shows a
    sentence. Treating that as "count not visible" would leave exactly the
    account that most needs classifying unclassified.
    """
    xml = (_FIXTURES / "cold_account_empty_friends_list.xml").read_text()

    result = u2_exec_mod._fb_read_count(xml, "friends")

    assert result["found"] is True
    assert result["value"] == 0
    assert result["source"] == "empty_state"


def test_followers_use_their_own_vocabulary() -> None:
    assert (
        u2_exec_mod._fb_read_count(_labels_xml("1,5K người theo dõi"), "followers")[
            "value"
        ]
        == 1500
    )
    # A friend count must not answer a follower question.
    assert (
        u2_exec_mod._fb_read_count(_labels_xml("248 bạn bè"), "followers")["found"]
        is False
    )


def test_unsupported_platform_is_reported_not_guessed() -> None:
    result = u2_exec_mod._flow_social_sync_connections(object(), {"platform": "vk"})
    assert result["found"] is False
    assert result["reason"] == "unsupported_platform"


# ── the account's own display name ──────────────────────────────────────────
#
# Captured from a real vivo V2352A (Vietnamese Facebook, 2026-09). Everything
# below is what that dump actually contains; none of it is hand-written.

_OWN_PROFILE = _FIXTURES / "own_profile_header_vn.xml"


def _own_profile_xml() -> str:
    return _OWN_PROFILE.read_text(encoding="utf-8")


def _root(xml: str):
    return u2_exec_mod._xml_parse_root(xml)


def test_vietnamese_profile_header_says_nguoi_ban_not_ban_be() -> None:
    """The wording this build prints, which the count reader used to miss.

    "2 người bạn" was read as "count not visible" on every Vietnamese device —
    silently, so the account stayed unclassified and nothing looked broken.
    """
    result = u2_exec_mod._fb_read_count(_own_profile_xml(), "friends")

    assert result["found"] is True
    assert result["value"] == 2
    assert result["evidence"] == "2 người bạn"


def test_reads_the_owner_name_between_the_avatar_and_the_first_action() -> None:
    assert u2_exec_mod._fb_profile_owner_name(_root(_own_profile_xml())) == {
        "found": True,
        "value": "Ngân Thanh Thanh Võ",
        "source": "profile_header",
    }


def test_the_split_count_row_is_not_mistaken_for_the_name() -> None:
    """The header renders the count as a button plus two views, "2" and
    "người bạn", both sitting directly above the name."""
    labels = u2_exec_mod._fb_all_labels(_root(_own_profile_xml()))

    assert "2" in labels and "người bạn" in labels


def test_a_stranger_profile_is_refused_rather_than_recorded_as_our_own() -> None:
    """Same header, the one difference that matters: no own-profile control.

    Somebody else's profile has "Thêm bạn bè" where ours has "Chỉnh sửa trang
    cá nhân". Reading the name anyway would store a stranger as the account's
    display name.
    """
    xml = _own_profile_xml().replace("Chỉnh sửa trang cá nhân", "Thêm bạn bè")
    xml = xml.replace("Thêm vào tin", "Nhắn tin")

    result = u2_exec_mod._fb_profile_owner_name(_root(xml))

    assert result == {"found": False, "reason": "not_own_profile"}


def test_a_scrolled_header_is_refused_rather_than_guessed() -> None:
    """Scroll past the avatar and the upper bound is gone. Without it the
    nearest label above the action row is whatever the page happens to show."""
    root = _root(_own_profile_xml())
    for node in root.iter("node"):
        folded = u2_exec_mod._fb_fold(u2_exec_mod._fb_node_label(node))
        if u2_exec_mod._FB_PROFILE_HEADER_CHROME.matches_folded(folded):
            node.attrib["text"] = ""
            node.attrib["content-desc"] = ""

    result = u2_exec_mod._fb_profile_owner_name(root)

    assert result == {"found": False, "reason": "profile_header_not_recognised"}


def test_the_home_feed_is_not_a_profile() -> None:
    xml = (_FIXTURES / "claude_vn_inline_comment_feed.xml").read_text()

    assert u2_exec_mod._fb_profile_owner_name(_root(xml))["found"] is False
