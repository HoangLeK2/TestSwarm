from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


def _load_agent_writer():
    path = Path(__file__).parents[2] / "agent-boot" / "relay" / "extra_data" / "writer.py"
    spec = importlib.util.spec_from_file_location("agent_content_writer_baseline", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _content_registry():
    from services.content.registry import seed_registry

    seed_registry()
    yield
    seed_registry([])


@dataclass
class _Result:
    row: Any = None
    rows: list[Any] | None = None
    rowcount: int = 0

    def first(self):
        return self.row

    def mappings(self):
        return self

    def all(self):
        return list(self.rows or [])


class _FakeSession:
    def __init__(self, identity: dict[str, Any] | None = None) -> None:
        self.insert_payload: list[dict[str, Any]] | None = None
        self.entity_org_id: str | None = None
        self.identity_params: dict[str, Any] | None = None
        self._identity = identity

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM relay_agents" in sql:
            self.identity_params = dict(params or {})
            return _Result(
                row=self._identity
                or {
                    "org_id": "org-server",
                    "user_id": "user-server",
                    "execution_id": None,
                    "campaign_id": None,
                    "account_id": None,
                    "device_id": None,
                }
            )
        if "INSERT INTO content_items" in sql:
            import json

            self.insert_payload = json.loads((params or {})["rows"])
            return _Result(
                rows=[
                    {
                        "content_hash": row["content_hash"],
                        "collection": row["collection"],
                        "user_id": row["user_id"],
                        "org_id": row["org_id"],
                        "platform": row["platform"],
                        "content_type": row["content_type"],
                    }
                    for row in self.insert_payload
                ]
            )
        if "INSERT INTO content_collections" in sql:
            return _Result()
        if "raw_data->>'_pid'" in sql:
            return _Result(row={"content_hash": "parent-server-hash"})
        if "UPDATE content_items" in sql:
            return _Result(rowcount=1)
        if "INSERT INTO external_entities" in sql:
            self.entity_org_id = (params or {})["org_id"]
            return _Result(
                rows=[
                    {
                        "id": "entity-1",
                        "platform": "facebook",
                        "entity_type": "group",
                        "identity_key": "group:1",
                    }
                ]
            )
        if "INSERT INTO external_entity_observations" in sql:
            return _Result()
        if "INSERT INTO external_entity_discoveries" in sql:
            return _Result()
        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_persist_edge_batch_hashes_raw_before_scrub_and_owns_tenant(monkeypatch):
    from services.content import edge_ingest
    from services.content_store import compute_content_hash, scope_content_hash

    session = _FakeSession()

    @asynccontextmanager
    async def fake_session():
        yield session

    monkeypatch.setattr(edge_ingest, "edge_ingest_session", fake_session)

    raw = {
        "platform": "facebook",
        "content_type": "fb_post",
        "body": "hello",
        "access_token": "sk-abcdefghijklmnopqrstuvwxyz1234",
    }
    expected_hash = scope_content_hash(compute_content_hash(raw), "execution-scope")

    result = await edge_ingest.persist_edge_batch(
        relay_id="relay-1",
        batch={
            "schema_version": 1,
            "kind": "content",
            "items": [raw],
            "content_hashes": [expected_hash],
        },
        trusted_context={
            "collection": "posts",
            "platform": "facebook",
            "content_type": "fb_post",
            "hash_scope": "execution-scope",
            "org_id": "org-spoofed",
            "user_id": "user-spoofed",
        },
    )

    assert result["inserted_count"] == 1
    assert result["duplicate_count"] == 0
    assert result["inserted_content_hashes"] == [expected_hash]
    assert session.insert_payload is not None
    row = session.insert_payload[0]
    agent_row = _load_agent_writer().build_content_item_row(
        raw,
        {
            "collection": "posts",
            "platform": "facebook",
            "content_type": "fb_post",
            "hash_scope": "execution-scope",
        },
    )
    assert row["content_hash"] == expected_hash
    for field in (
        "collection",
        "platform",
        "content_type",
        "title",
        "body",
        "author",
        "parent_id",
        "item_level",
    ):
        assert row[field] == agent_row[field]
    assert row["org_id"] == "org-server"
    assert row["user_id"] == "user-server"
    assert row["raw_data"]["access_token"] == "[REDACTED_OPENAI_KEY]"


@pytest.mark.asyncio
async def test_persist_edge_batch_keeps_campaign_and_account_without_execution(monkeypatch):
    """A crawl outside an execution must still record what it belongs to.

    device_farm resolves and validates campaign_id/account_id before the request
    leaves (see extraction.py::_resolve_campaign_id_for_edge), so deriving them
    from the execution alone silently dropped them for any run that has no
    execution — the crawl saved its rows, but orphaned.
    """
    from services.content import edge_ingest
    from services.content_store import compute_content_hash, scope_content_hash

    # Identity as the SQL returns it once COALESCE picks up the joined campaign
    # and account for a run with no execution row.
    session = _FakeSession(
        identity={
            "org_id": "org-server",
            "user_id": "user-server",
            "execution_id": None,
            "campaign_id": "campaign-7",
            "account_id": "account-9",
            "device_id": None,
        }
    )

    @asynccontextmanager
    async def fake_session():
        yield session

    monkeypatch.setattr(edge_ingest, "edge_ingest_session", fake_session)

    raw = {"platform": "facebook", "content_type": "fb_post", "body": "hello"}
    expected_hash = scope_content_hash(compute_content_hash(raw), "run-scope")

    await edge_ingest.persist_edge_batch(
        relay_id="relay-1",
        batch={
            "schema_version": 1,
            "kind": "content",
            "items": [raw],
            "content_hashes": [expected_hash],
        },
        trusted_context={
            "collection": "posts",
            "platform": "facebook",
            "content_type": "fb_post",
            "hash_scope": "run-scope",
            "campaign_id": "campaign-7",
            "account_id": "account-9",
        },
    )

    # Both must reach the identity query, or the joins can never match them.
    assert session.identity_params is not None
    assert session.identity_params["campaign_id"] == "campaign-7"
    assert session.identity_params["account_id"] == "account-9"

    assert session.insert_payload is not None
    row = session.insert_payload[0]
    assert row["campaign_id"] == "campaign-7"
    assert row["account_id"] == "account-9"
    assert row["execution_id"] is None


@pytest.mark.asyncio
async def test_persist_edge_batch_rejects_hash_not_derived_from_raw(monkeypatch):
    from services.content import edge_ingest

    session = _FakeSession()

    @asynccontextmanager
    async def fake_session():
        yield session

    monkeypatch.setattr(edge_ingest, "edge_ingest_session", fake_session)

    with pytest.raises(edge_ingest.ContentUplinkError, match="content hash"):
        await edge_ingest.persist_edge_batch(
            relay_id="relay-1",
            batch={
                "schema_version": 1,
                "kind": "content",
                "items": [{"body": "untampered"}],
                "content_hashes": ["client-forged-hash"],
            },
            trusted_context={
                "collection": "posts",
                "platform": "facebook",
                "content_type": "fb_post",
            },
        )

    assert session.insert_payload is None


@pytest.mark.asyncio
async def test_persist_edge_batch_resolves_parent_and_updates_stats_in_farm(monkeypatch):
    from services.content import edge_ingest
    from services.content_store import compute_content_hash, scope_content_hash

    session = _FakeSession()

    @asynccontextmanager
    async def fake_session():
        yield session

    monkeypatch.setattr(edge_ingest, "edge_ingest_session", fake_session)
    raw = {"text": "comment", "parent_post_id": "pid-1"}
    content_hash = scope_content_hash(compute_content_hash(raw), "exec-scope")

    result = await edge_ingest.persist_edge_batch(
        relay_id="relay-1",
        batch={
            "schema_version": 1,
            "kind": "content",
            "items": [raw],
            "content_hashes": [content_hash],
            "parent_hint": {
                "parent_post_id": "pid-1",
                "require_verified_parent": True,
            },
            "post_stats": {"reactions": "12", "comments": "3", "shares": "2"},
        },
        trusted_context={
            "collection": "comments",
            "platform": "facebook",
            "content_type": "fb_comment",
            "hash_scope": "exec-scope",
            "item_level": 1,
        },
    )

    assert result["inserted_count"] == 1
    assert result["parent_stats_updated"] is True
    assert session.insert_payload is not None
    assert session.insert_payload[0]["parent_id"] == "parent-server-hash"


@pytest.mark.asyncio
async def test_persist_edge_batch_bulk_upserts_entities_under_relay_org(monkeypatch):
    from services.content import edge_ingest

    session = _FakeSession()

    @asynccontextmanager
    async def fake_session():
        yield session

    monkeypatch.setattr(edge_ingest, "edge_ingest_session", fake_session)
    result = await edge_ingest.persist_edge_batch(
        relay_id="relay-1",
        batch={
            "schema_version": 1,
            "kind": "entities",
            "captured_at": "2026-08-27T01:02:03+00:00",
            "items": [
                {
                    "platform": "facebook",
                    "entity_type": "group",
                    "identity_key": "group:1",
                    "display_name": "Group One",
                    "raw_data": {"token": "sk-abcdefghijklmnopqrstuvwxyz1234"},
                }
            ],
        },
        trusted_context={"search_query": "groups", "source_index": 2},
    )

    assert session.entity_org_id == "org-server"
    assert result["inserted_count"] == 1
    assert result["observation_count"] == 1
    assert result["discovery_count"] == 1
    assert result["entity_ids"] == ["entity-1"]
