from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from api.routes.content import (
    _is_parent_post_body_child,
    _item_to_out_with_parent,
    _parent_post_identifiers,
    _resolve_parent_item,
    _resolve_parent_items_for_list,
)


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
        platform="instagram",
        content_type="ig_comment",
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
        content_type="ig_media",
    )

    out = _item_to_out_with_parent(item, parent_item=parent)

    assert out["parent_id"] == "stale-parent-hash"
    assert out["parent_item_id"] == "post-id"
    assert out["parent_item_hash"] == "real-post-hash"
    assert out["parent_item_author"] == "Alice"
    assert out["parent_item_body"] == "parent post body"


def test_parent_post_body_child_detects_post_content_saved_as_comment() -> None:
    parent = SimpleNamespace(
        content_type="platform_items",
        author="Vũ Nguyễn Thiên Ân",
        body="Mình đang dùng gói 20x và sau",
        title=None,
        raw_data={},
    )
    bad_child = SimpleNamespace(
        content_type="ig_comment",
        item_level=1,
        author="Vũ Nguyễn Thiên Ân",
        body="Mình đang dùng gói 20x và sau ... xem thêm Ảnh",
        raw_data={},
    )
    real_child = SimpleNamespace(
        content_type="ig_comment",
        item_level=1,
        author="Nguyễn A",
        body="Comment thật trong bài",
        raw_data={},
    )

    assert _is_parent_post_body_child(parent, bad_child) is True
    assert _is_parent_post_body_child(parent, real_child) is False


@pytest.mark.asyncio
async def test_resolve_parent_item_returns_none_without_definite_link() -> None:
    comment = SimpleNamespace(
        content_type="ig_comment",
        platform="instagram",
        parent_id=None,
        item_level=0,
        raw_data={"parent_post_id": "orphan-pid"},
        user_id="user-1",
        org_id="org-1",
        collection="instagram",
        execution_id="exec-1",
        extracted_at=datetime(2026, 6, 3, 9, 50, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 3, 9, 50, 1, tzinfo=timezone.utc),
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class FakeDb:
        def __init__(self) -> None:
            self.statements = []
            self.results = [None, None]

        async def execute(self, stmt):
            self.statements.append(str(stmt))
            return Result(self.results.pop(0) if self.results else None)

    db = FakeDb()

    assert await _resolve_parent_item(db, comment) is None


@pytest.mark.asyncio
async def test_resolve_parent_items_for_list_matches_by_parser_pid() -> None:
    comment = SimpleNamespace(
        id="comment-id",
        content_type="ig_comment",
        parent_id=None,
        item_level=1,
        raw_data={"parent_post_id": "pid-abc"},
        user_id="user-1",
        org_id="org-1",
        collection="fb",
        execution_id="exec-1",
        extracted_at=datetime(2026, 6, 3, 9, 50, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 3, 9, 50, 1, tzinfo=timezone.utc),
    )
    matched_post = SimpleNamespace(
        id="matched-post",
        content_hash="matched-hash",
        content_type="platform_items",
        parent_id=None,
        item_level=0,
        raw_data={"_pid": "pid-abc"},
        user_id="user-1",
        org_id="org-1",
        collection="fb",
        execution_id="exec-1",
        extracted_at=datetime(2026, 6, 3, 9, 49, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 3, 9, 49, 1, tzinfo=timezone.utc),
    )

    class ScalarRows:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return ScalarRows(self.rows)

    class FakeDb:
        async def execute(self, stmt):
            return Result([matched_post])

    resolved = await _resolve_parent_items_for_list(FakeDb(), [comment])

    assert resolved == {"comment-id": matched_post}
