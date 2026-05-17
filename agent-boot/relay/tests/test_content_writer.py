from __future__ import annotations

from datetime import datetime, timezone

import pytest

from relay.extra_data.writer import (
    ContentItemWriter,
    build_content_item_row,
    compute_content_hash,
    scope_content_hash,
)


def test_hash_matches_content_store_contract() -> None:
    data = {"post_key": "abc", "text": "hello"}
    base = compute_content_hash(data, dedupe_field="post_key")

    assert compute_content_hash({"b": 2, "a": 1}) == compute_content_hash({"a": 1, "b": 2})
    assert scope_content_hash(base, "run-1") != base
    assert scope_content_hash(base, "run-1") == scope_content_hash(base, "run-1")


def test_build_content_item_row_maps_fields_and_scopes_hash() -> None:
    captured = datetime(2026, 5, 15, 4, 0, tzinfo=timezone.utc)
    row = build_content_item_row(
        {
            "post_key": "p1",
            "text": "  hello  ",
            "author": " Alice ",
            "reactions": "1.2K",
            "comments": "3",
            "shares": "4",
            "views": "5K",
            "timestamp": "2 hours ago",
            "media_artifacts": ["https://example.test/a.jpg"],
        },
        {
            "collection": "fb",
            "platform": "facebook",
            "content_type": "post",
            "device_serial": "serial-1",
            "campaign_id": "camp",
            "execution_id": "exec",
            "user_id": "user",
            "scenario_name": "scenario",
            "hash_scope": "scope",
            "dedupe_field": "post_key",
        },
        captured_at=captured,
    )

    assert row["collection"] == "fb"
    assert row["body"] == "hello"
    assert row["author"] == "Alice"
    assert row["likes_count"] == 1200
    assert row["comments_count"] == 3
    assert row["shares_count"] == 4
    assert row["views_count"] == 5000
    assert row["media_urls"] == ["https://example.test/a.jpg"]
    assert row["content_date"] == datetime(2026, 5, 15, 2, 0, tzinfo=timezone.utc)
    assert row["content_hash"] == scope_content_hash(compute_content_hash({"post_key": "p1", "text": "  hello  ", "author": " Alice ", "reactions": "1.2K", "comments": "3", "shares": "4", "views": "5K", "timestamp": "2 hours ago", "media_artifacts": ["https://example.test/a.jpg"]}, "post_key"), "scope")


def test_parent_hash_is_scoped_for_comments() -> None:
    row = build_content_item_row(
        {"comment_key": "c1", "text": "comment"},
        {
            "collection": "fb",
            "content_type": "comment",
            "hash_scope": "scope",
            "dedupe_field": "comment_key",
        },
        parent_id="parent-base-hash",
        item_level=1,
    )

    assert row["item_level"] == 1
    assert row["parent_id"] == scope_content_hash("parent-base-hash", "scope")


@pytest.mark.asyncio
async def test_insert_rows_batches_and_increments_collection_count() -> None:
    class _Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Acquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Conn:
        def __init__(self):
            self.fetch_sql = ""
            self.fetch_payload = ""
            self.executed = []

        def transaction(self):
            return _Tx()

        async def fetch(self, sql, payload):
            self.fetch_sql = sql
            self.fetch_payload = payload
            return [{
                "collection": "fb",
                "user_id": "u1",
                "platform": "facebook",
                "content_type": "post",
                "inserted_count": 2,
            }]

        async def execute(self, *args):
            self.executed.append(args)
            return "INSERT 0 1"

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return _Acquire(self.conn)

    conn = _Conn()
    writer = ContentItemWriter(database_url="postgres://example")
    writer._pool = _Pool(conn)
    rows = [
        build_content_item_row({"post_key": "p1", "text": "one"}, {"collection": "fb", "user_id": "u1"}),
        build_content_item_row({"post_key": "p2", "text": "two"}, {"collection": "fb", "user_id": "u1"}),
    ]

    result = await writer.insert_rows(rows)

    assert result == {"attempted": 2, "inserted": 2, "duplicates": 0}
    assert "jsonb_to_recordset" in conn.fetch_sql
    assert '"post_key": "p1"' in conn.fetch_payload
    assert len(conn.executed) == 1
    assert "content_collections" in conn.executed[0][0]
    assert "item_count = content_collections.item_count + EXCLUDED.item_count" in conn.executed[0][0]
