from __future__ import annotations

from types import SimpleNamespace

from api.routes.content import _item_to_out_with_parent, _parent_post_identifiers


def test_parent_post_identifiers_reads_comment_anchor() -> None:
    item = SimpleNamespace(
        raw_data={
            "parent_post_id": "pid-1",
            "parent_post_anchor": {
                "post_key": "post-key-1",
                "pid": "pid-anchor",
                "stable_post_id": "stable-1",
            },
        }
    )

    assert _parent_post_identifiers(item) == [
        ("post_key", "post-key-1"),
        ("_pid", "pid-anchor"),
        ("stable_post_id", "stable-1"),
    ]


def test_item_to_out_includes_resolved_parent_summary() -> None:
    item = SimpleNamespace(
        id="comment-id",
        collection="fb",
        platform="facebook",
        content_type="fb_comment",
        title=None,
        body="comment body",
        author="Bob",
        author_id=None,
        url=None,
        likes_count=None,
        comments_count=None,
        shares_count=None,
        views_count=None,
        media_urls=[],
        screenshot_path=None,
        tags="",
        raw_data={},
        device_serial=None,
        campaign_id=None,
        execution_id="exec-1",
        scenario_name=None,
        extracted_at=None,
        content_date=None,
        created_at=None,
        content_hash="comment-hash",
        parent_id="stale-parent-hash",
        item_level=1,
    )
    parent = SimpleNamespace(
        id="post-id",
        content_hash="real-post-hash",
        author="Alice",
        body="parent post body",
        content_type="fb_post",
    )

    out = _item_to_out_with_parent(item, parent_item=parent)

    assert out["parent_id"] == "stale-parent-hash"
    assert out["parent_item_id"] == "post-id"
    assert out["parent_item_hash"] == "real-post-hash"
    assert out["parent_item_author"] == "Alice"
    assert out["parent_item_body"] == "parent post body"
