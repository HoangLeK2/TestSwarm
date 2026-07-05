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
    raw = {
        "post_key": "p1",
        "text": "  hello  ",
        "author": " Alice ",
        "reactions": "1.2K",
        "comments": "3",
        "shares": "4",
        "views": "5K",
        "timestamp": "2 hours ago",
        "media_artifacts": ["https://example.test/a.jpg"],
    }
    row = build_content_item_row(
        raw,
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
    assert row["raw_data"] == raw
    assert row["content_date"] == datetime(2026, 5, 15, 2, 0, tzinfo=timezone.utc)
    assert row["content_hash"] == scope_content_hash(compute_content_hash(raw, "post_key"), "scope")


def test_build_content_item_row_parses_vietnamese_decimal_suffix_counts() -> None:
    row = build_content_item_row(
        {"post_key": "p1", "text": "hello", "reactions": "60,5K"},
        {"collection": "fb", "content_type": "post"},
    )

    assert row["likes_count"] == 60500


@pytest.mark.asyncio
async def test_update_content_stats_updates_existing_root_post() -> None:
    class _Acquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Conn:
        def __init__(self):
            self.fetchrow_calls = []

        async def fetchrow(self, *args):
            self.fetchrow_calls.append(args)
            return {"content_hash": "parent-hash"}

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return _Acquire(self.conn)

    conn = _Conn()
    writer = ContentItemWriter(database_url="postgres://example")
    writer._pool = _Pool(conn)

    updated = await writer.update_content_stats(
        content_hash="parent-hash",
        likes_count="12",
        comments_count="60,5K",
        shares_count="2",
    )

    assert updated is True
    sql, content_hash, likes, comments, shares = conn.fetchrow_calls[0]
    assert "UPDATE content_items" in sql
    assert "item_level = 0" in sql
    assert content_hash == "parent-hash"
    assert likes == 12
    assert comments == 60500
    assert shares == 2


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
            if "FROM users" in sql:
                return [{"id": uid} for uid in (payload or []) if uid]
            if "FROM organizations" in sql:
                return [{"id": oid} for oid in (payload or []) if oid]
            return []

        async def fetchrow(self, sql, payload):
            import json

            self.fetch_sql = sql
            self.fetch_payload = payload
            data = json.loads(payload)
            hashes = [str(item["content_hash"]) for item in data]
            return {"inserted_hashes": hashes, "inserted_count": len(hashes)}

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
        build_content_item_row(
            {"post_key": "p1", "text": "one"},
            {"collection": "fb", "user_id": "u1", "org_id": "org-1"},
        ),
        build_content_item_row(
            {"post_key": "p2", "text": "two"},
            {"collection": "fb", "user_id": "u1", "org_id": "org-1"},
        ),
    ]

    result = await writer.insert_rows(rows)

    assert result["attempted"] == 2
    assert result["inserted"] == 2
    assert result["duplicates"] == 0
    assert result["inserted_content_hashes"] == [rows[0]["content_hash"], rows[1]["content_hash"]]
    assert "jsonb_to_recordset" in conn.fetch_sql
    assert '"post_key": "p1"' in conn.fetch_payload
    assert len(conn.executed) == 1
    assert "content_collections" in conn.executed[0][0]
    assert "item_count = content_collections.item_count + EXCLUDED.item_count" in conn.executed[0][0]
    assert "uq_content_collections_org_name_user" in conn.executed[0][0]


@pytest.mark.asyncio
async def test_insert_rows_drops_stale_campaign_id() -> None:
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
            self.fetch_calls = []
            self.executed = []

        def transaction(self):
            return _Tx()

        async def fetch(self, sql, payload):
            self.fetch_calls.append((sql, payload))
            if "FROM campaigns" in sql:
                return []
            return []

        async def fetchrow(self, sql, payload):
            self.fetch_calls.append((sql, payload))
            return {"inserted_hashes": ["hash-1"], "inserted_count": 1}

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
    row = build_content_item_row(
        {"post_key": "p1", "text": "one"},
        {"collection": "fb", "user_id": "u1", "campaign_id": "missing-campaign"},
    )

    result = await writer.insert_rows([row])

    assert result["inserted"] == 1
    assert row["campaign_id"] is None
    assert any("FROM campaigns" in sql for sql, _ in conn.fetch_calls)
    assert '"campaign_id": null' in conn.fetch_calls[-1][1]


@pytest.mark.asyncio
async def test_insert_rows_drops_campaign_id_when_campaign_lookup_fails() -> None:
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
            self.fetch_calls = []
            self.executed = []

        def transaction(self):
            return _Tx()

        async def fetch(self, sql, payload):
            self.fetch_calls.append((sql, payload))
            if "FROM campaigns" in sql:
                raise PermissionError("permission denied for table campaigns")
            return []

        async def fetchrow(self, sql, payload):
            self.fetch_calls.append((sql, payload))
            return {"inserted_hashes": ["hash-1"], "inserted_count": 1}

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
    row = build_content_item_row(
        {"post_key": "p1", "text": "one"},
        {"collection": "fb", "user_id": "u1", "campaign_id": "maybe-stale"},
    )

    result = await writer.insert_rows([row])

    assert result["inserted"] == 1
    assert row["campaign_id"] is None
    assert '"campaign_id": null' in conn.fetch_calls[-1][1]


@pytest.mark.asyncio
async def test_insert_rows_retries_without_campaign_id_on_fk_violation() -> None:
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
            self.fetch_calls = []
            self.executed = []
            self.insert_attempts = 0

        def transaction(self):
            return _Tx()

        async def fetch(self, sql, payload):
            self.fetch_calls.append((sql, payload))
            if "FROM campaigns" in sql:
                # Simulate race: preflight sees row, insert FK still fails.
                return [{"id": "missing-campaign"}]
            if "FROM users" in sql:
                return [{"id": "u1"}]
            if "FROM executions" in sql:
                return []
            return []

        async def fetchrow(self, sql, payload):
            self.fetch_calls.append((sql, payload))
            self.insert_attempts += 1
            if self.insert_attempts == 1:
                raise Exception(
                    'insert or update on table "content_items" violates foreign key constraint '
                    '"content_items_campaign_id_fkey"'
                )
            return {"inserted_hashes": ["hash-1"], "inserted_count": 1}

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
    row = build_content_item_row(
        {"post_key": "p1", "text": "one"},
        {"collection": "fb", "user_id": "u1", "campaign_id": "missing-campaign"},
    )

    result = await writer.insert_rows([row])

    assert result["inserted"] == 1
    assert row["campaign_id"] is None
    assert conn.insert_attempts == 2
    assert '"campaign_id": null' in conn.fetch_calls[-1][1]


@pytest.mark.asyncio
async def test_sanitize_campaign_id_drops_missing() -> None:
    class _Acquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Conn:
        async def fetch(self, sql, payload):
            if "FROM campaigns" in sql:
                return []
            return []

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return _Acquire(self.conn)

    writer = ContentItemWriter(database_url="postgres://example")
    writer._pool = _Pool(_Conn())

    assert await writer.sanitize_campaign_id("missing-campaign") is None
    assert await writer.sanitize_campaign_id("  ") is None


@pytest.mark.asyncio
async def test_sanitize_campaign_id_keeps_existing() -> None:
    class _Acquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Conn:
        async def fetch(self, sql, payload):
            if "FROM campaigns" in sql:
                return [{"id": "camp-1"}]
            return []

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return _Acquire(self.conn)

    writer = ContentItemWriter(database_url="postgres://example")
    writer._pool = _Pool(_Conn())

    assert await writer.sanitize_campaign_id("camp-1") == "camp-1"


@pytest.mark.asyncio
async def test_prepare_context_for_persist_resolves_org_from_user() -> None:
    class _Acquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Conn:
        async def fetchrow(self, sql, user_id):
            assert user_id == "user-1"
            return {"org_id": "org-1"}

        async def fetch(self, sql, payload):
            if "organizations" in sql:
                return [{"id": "org-1"}]
            if "users" in sql:
                return [{"id": "user-1"}]
            return []

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return _Acquire(self.conn)

    writer = ContentItemWriter(database_url="postgres://example")
    writer._pool = _Pool(_Conn())

    context = await writer.prepare_context_for_persist({
        "user_id": "user-1",
        "collection": "fb",
    })

    assert context["org_id"] == "org-1"
    assert context["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_prepare_context_for_persist_strips_stale_fks() -> None:
    class _Acquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Conn:
        async def fetch(self, sql, payload):
            return []

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return _Acquire(self.conn)

    writer = ContentItemWriter(database_url="postgres://example")
    writer._pool = _Pool(_Conn())

    context = await writer.prepare_context_for_persist({
        "campaign_id": "missing-campaign",
        "execution_id": "missing-exec",
        "user_id": "missing-user",
        "collection": "fb",
    })

    assert context["campaign_id"] is None
    assert context["execution_id"] is None
    assert context["user_id"] is None
    assert context["collection"] == "fb"


@pytest.mark.asyncio
async def test_insert_rows_strips_stale_execution_id() -> None:
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
            self.fetch_calls = []

        def transaction(self):
            return _Tx()

        async def fetch(self, sql, payload):
            self.fetch_calls.append((sql, payload))
            if "FROM campaigns" in sql or "FROM executions" in sql or "FROM users" in sql:
                return []
            return []

        async def fetchrow(self, sql, payload):
            self.fetch_calls.append((sql, payload))
            return {"inserted_hashes": ["hash-1"], "inserted_count": 1}

        async def execute(self, *args):
            return "INSERT 0 1"

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return _Acquire(self.conn)

    conn = _Conn()
    writer = ContentItemWriter(database_url="postgres://example")
    writer._pool = _Pool(conn)
    row = build_content_item_row(
        {"post_key": "p1", "text": "one"},
        {
            "collection": "fb",
            "execution_id": "missing-exec",
            "campaign_id": "missing-campaign",
        },
    )

    result = await writer.insert_rows([row])

    assert result["inserted"] == 1
    assert row["campaign_id"] is None
    assert row["execution_id"] is None
    assert '"execution_id": null' in conn.fetch_calls[-1][1]
