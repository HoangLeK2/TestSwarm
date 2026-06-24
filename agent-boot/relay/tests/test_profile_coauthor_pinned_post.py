from __future__ import annotations

from pathlib import Path

from relay.extra_data.parsers.facebook.feed_pipeline import parse_fb_posts_from_xml_with_diagnostic

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "facebook"
    / "mtp_profile_coauthor_pinned.xml"
)


def test_pinned_coauthor_post_author_is_poster_not_pin_chrome() -> None:
    """M-TP profile: pinned row 'Bài viết đã ghim•23 thg 5' must not become author."""
    xml = _FIXTURE.read_text(encoding="utf-8")
    posts, diag = parse_fb_posts_from_xml_with_diagnostic(xml)
    assert diag["reason_code"] == "ok"
    assert len(posts) >= 1
    post = posts[0]
    assert post["author"] == "M-TP"
    assert "ghim" not in post["author"].lower()
    assert "tyga" not in post["author"].lower()
    assert "23 thg 5" in post["timestamp"]
    assert "COME MY WAY" in post["text"]
