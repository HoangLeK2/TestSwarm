from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from api.routes.content import (
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


@pytest.mark.asyncio
async def test_resolve_parent_item_uses_previous_post_in_same_execution_timeline() -> None:
    comment = SimpleNamespace(
        content_type="fb_comment",
        parent_id=None,
        item_level=0,
        raw_data={"parent_post_id": "stale-parser-pid"},
        user_id="user-1",
        org_id="org-1",
        collection="fb",
        execution_id="exec-1",
        extracted_at=datetime(2026, 6, 3, 9, 50, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 3, 9, 50, 1, tzinfo=timezone.utc),
    )
    parent = SimpleNamespace(id="post-id", content_hash="post-hash")

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class FakeDb:
        def __init__(self) -> None:
            self.statements = []
            self.results = [None, None, parent]

        async def execute(self, stmt):
            self.statements.append(str(stmt))
            return Result(self.results.pop(0))

    db = FakeDb()

    assert await _resolve_parent_item(db, comment) is parent
    assert len(db.statements) == 3
    assert "content_items.raw_data" in db.statements[0]
    statement = db.statements[-1]
    assert "content_items.execution_id = :execution_id_1" in statement
    assert "content_items.collection = :collection_1" in statement
    assert "content_items.extracted_at <= :extracted_at_1" in statement
    assert "content_items.extracted_at DESC" in statement


@pytest.mark.asyncio
async def test_resolve_parent_items_for_list_batches_timeline_parent() -> None:
    comment = SimpleNamespace(
        id="comment-id",
        content_type="fb_comment",
        parent_id=None,
        item_level=1,
        raw_data={"parent_post_id": "stale-parser-pid"},
        user_id="user-1",
        org_id="org-1",
        collection="fb",
        execution_id="exec-1",
        extracted_at=datetime(2026, 6, 3, 9, 50, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 3, 9, 50, 1, tzinfo=timezone.utc),
    )
    previous_post = SimpleNamespace(
        id="previous-post",
        content_hash="previous-hash",
        content_type="fb_post",
        parent_id=None,
        item_level=0,
        user_id="user-1",
        org_id="org-1",
        collection="fb",
        execution_id="exec-1",
        extracted_at=datetime(2026, 6, 3, 9, 49, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 3, 9, 49, 1, tzinfo=timezone.utc),
    )
    newer_post = SimpleNamespace(
        id="newer-post",
        content_hash="newer-hash",
        content_type="fb_post",
        parent_id=None,
        item_level=0,
        user_id="user-1",
        org_id="org-1",
        collection="fb",
        execution_id="exec-1",
        extracted_at=datetime(2026, 6, 3, 9, 51, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 3, 9, 51, 1, tzinfo=timezone.utc),
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
        def __init__(self) -> None:
            self.statements = []

        async def execute(self, stmt):
            self.statements.append(str(stmt))
            return Result([newer_post, previous_post])

    db = FakeDb()

    resolved = await _resolve_parent_items_for_list(db, [comment])

    assert resolved == {"comment-id": previous_post}
    assert len(db.statements) == 1
    assert "content_items.execution_id IN" in db.statements[0]
