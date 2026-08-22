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
