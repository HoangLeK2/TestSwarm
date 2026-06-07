from __future__ import annotations

from pathlib import Path

from relay.extra_data.parsers.facebook.feed_pipeline import parse_fb_posts_from_xml_with_diagnostic

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "vivo_comment_sheet_kent_juno_post.xml"


def test_comment_sheet_post_author_is_poster_not_group_name() -> None:
    xml = _FIXTURE.read_text(encoding="utf-8")
    posts, diag = parse_fb_posts_from_xml_with_diagnostic(xml)
    assert diag["reason_code"] == "ok"
    assert len(posts) == 1
    post = posts[0]
    assert post["author"] == "Kent Juno"
    assert post["timestamp"] == "1 ngày•Chia sẻ với: Nhóm công khai"
    assert "openclaw vn" not in post["author"].lower()
