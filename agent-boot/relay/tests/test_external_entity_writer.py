import json

import pytest

from relay.extra_data.entity_writer import ExternalEntityWriter


class _AsyncContext:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _Connection:
    def __init__(self):
        self.fetch_calls = []
        self.execute_calls = []

    def transaction(self):
        return _AsyncContext()

    async def fetchval(self, sql, value):
        if "executions" in sql:
            assert value == "execution-a"
            return "org-a"
        return "org-a"

    async def fetch(self, sql, payload, org_id):
        self.fetch_calls.append((sql, json.loads(payload), org_id))
        return [
            {
                "id": "entity-1",
                "platform": "facebook",
                "entity_type": "group",
                "identity_key": "name:group one",
            },
            {
                "id": "entity-2",
                "platform": "facebook",
                "entity_type": "group",
                "identity_key": "name:group two",
            },
        ]

    async def execute(self, sql, payload, org_id):
        self.execute_calls.append((sql, json.loads(payload), org_id))
        return "INSERT 0 2"


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AsyncContext(self.conn)


@pytest.mark.asyncio
async def test_writer_uses_one_upsert_and_set_based_history_statements():
    conn = _Connection()

    async def pool_provider():
        return _Pool(conn)

    writer = ExternalEntityWriter(pool_provider)
    result = await writer.persist_items(
        [
            {
                "platform": "facebook",
                "entity_type": "group",
                "identity_key": "name:group one",
                "display_name": "Group One",
                "metrics": {"member_count": 10},
                "rank": 1,
            },
            {
                "platform": "facebook",
                "entity_type": "group",
                "identity_key": "name:group two",
                "display_name": "Group Two",
                "metrics": {"member_count": 20},
                "rank": 2,
            },
        ],
        context={
            "org_id": "org-a",
            "search_query": "automation",
            "execution_id": "execution-a",
        },
        captured_at="2026-07-26T00:00:00+00:00",
    )

    assert result["upserted"] == 2
    assert result["observed"] == 2
    assert result["discovered"] == 2
    assert len(conn.fetch_calls) == 1
    assert "ON CONFLICT (org_id, platform, entity_type, identity_key)" in conn.fetch_calls[0][0]
    assert len(conn.execute_calls) == 2
    assert "external_entity_observations" in conn.execute_calls[0][0]
    assert "ON CONFLICT" in conn.execute_calls[0][0]
    assert "external_entity_discoveries" in conn.execute_calls[1][0]
    assert "ON CONFLICT" in conn.execute_calls[1][0]


@pytest.mark.asyncio
async def test_writer_rejects_org_different_from_execution_owner():
    conn = _Connection()

    async def pool_provider():
        return _Pool(conn)

    writer = ExternalEntityWriter(pool_provider)
    with pytest.raises(ValueError, match="execution ownership"):
        await writer.persist_items(
            [
                {
                    "platform": "facebook",
                    "entity_type": "group",
                    "identity_key": "name:group one",
                    "display_name": "Group One",
                }
            ],
            context={
                "org_id": "org-b",
                "execution_id": "execution-a",
            },
        )


@pytest.mark.asyncio
async def test_writer_collapses_duplicate_entity_upserts_within_one_batch():
    conn = _Connection()

    async def pool_provider():
        return _Pool(conn)

    writer = ExternalEntityWriter(pool_provider)
    result = await writer.persist_items(
        [
            {
                "platform": "facebook",
                "entity_type": "group",
                "identity_key": "name:group one",
                "display_name": "Group One",
                "rank": 1,
            },
            {
                "platform": "facebook",
                "entity_type": "group",
                "identity_key": "name:group one",
                "display_name": "Group One",
                "rank": 2,
            },
        ],
        context={
            "org_id": "org-a",
            "search_query": "automation",
            "execution_id": "execution-a",
        },
    )

    assert result["attempted"] == 2
    assert result["observed"] == 1
    assert result["discovered"] == 1
    assert len(conn.fetch_calls) == 1
    assert len(conn.fetch_calls[0][1]) == 1
    assert len(conn.execute_calls) == 2
    assert len(conn.execute_calls[0][1]) == 1
    assert len(conn.execute_calls[1][1]) == 1
