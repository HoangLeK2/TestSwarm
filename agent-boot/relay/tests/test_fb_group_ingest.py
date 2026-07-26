import pytest

from relay.extra_data.ingest import ExtraDataIngestServer


def _group_page(*cards: tuple[str, int]) -> str:
    nodes = "".join(
        (
            '<node clickable="true" '
            f'content-desc="{name}, Công khai · {members} thành viên" />'
        )
        for name, members in cards
    )
    return f"<hierarchy>{nodes}</hierarchy>"


@pytest.mark.asyncio
async def test_process_payload_routes_fb_groups_to_entity_catalog(monkeypatch) -> None:
    server = ExtraDataIngestServer()

    async def prepare_context(context):
        return {**context, "org_id": "org-a"}

    async def persist_items(items, *, context, captured_at=None):
        assert context["search_query"] == "openclaw"
        assert [item["display_name"] for item in items] == ["OpenClaw VN"]
        return {
            "attempted": 1,
            "upserted": 1,
            "observed": 1,
            "discovered": 1,
            "entity_ids": ["entity-1"],
        }

    monkeypatch.setattr(server._writer, "prepare_context_for_persist", prepare_context)
    monkeypatch.setattr(server._entity_writer, "persist_items", persist_items)
    result = await server.process_payload(
        {
            "serial": "device-1",
            "strategy": "fb_groups",
            "xml": (
                '<hierarchy><node clickable="true" '
                'content-desc="OpenClaw VN, Nhóm Công khai · 100 thành viên" />'
                "</hierarchy>"
            ),
            "context": {
                "persist": True,
                "return_items": True,
                "search_query": "openclaw",
            },
        }
    )

    assert result["ok"] is True
    assert result["entity_ids"] == ["entity-1"]
    assert result["observation_count"] == 1
    assert result["discovery_count"] == 1
    assert result["items"][0]["display_name"] == "OpenClaw VN"


@pytest.mark.asyncio
async def test_process_payload_merges_all_group_crawl_snapshots_before_persist(
    monkeypatch,
) -> None:
    server = ExtraDataIngestServer()
    first = _group_page(("Group A", 100), ("Group B", 200))
    second = _group_page(("Group B", 250), ("Group C", 300))

    async def prepare_context(context):
        return {**context, "org_id": "org-a"}

    async def persist_items(items, *, context, captured_at=None):
        assert [item["display_name"] for item in items] == [
            "Group A",
            "Group B",
            "Group C",
        ]
        assert items[1]["metrics"]["member_count"] == 250
        return {
            "attempted": 3,
            "upserted": 3,
            "observed": 3,
            "discovered": 3,
            "entity_ids": ["entity-a", "entity-b", "entity-c"],
        }

    monkeypatch.setattr(server._writer, "prepare_context_for_persist", prepare_context)
    monkeypatch.setattr(server._entity_writer, "persist_items", persist_items)

    result = await server.process_payload(
        {
            "serial": "device-1",
            "strategy": "fb_groups",
            "xml": first,
            "xml_snapshots": [first, second],
            "context": {
                "persist": True,
                "return_items": True,
                "search_query": "group",
            },
        }
    )

    assert result["ok"] is True
    assert result["parsed_count"] == 3
    assert result["diagnostic"]["snapshot_count"] == 2
    assert result["diagnostic"]["groups_returned"] == 3
    assert [item["rank"] for item in result["items"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_group_snapshot_merge_keeps_richer_nested_fields(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    first = (
        '<hierarchy><node clickable="true" '
        'content-desc="Group A, Nhóm Công khai · 200 thành viên" />'
        "</hierarchy>"
    )
    sparse_duplicate = (
        '<hierarchy><node clickable="true" '
        'content-desc="Group A, Nhóm Công khai" />'
        "</hierarchy>"
    )

    async def prepare_context(context):
        return {**context, "org_id": "org-a"}

    async def persist_items(items, *, context, captured_at=None):
        assert items[0]["metrics"]["member_count"] == 200
        assert items[0]["attributes"]["privacy"] == "public"
        assert items[0]["attributes"]["locator"]["search_query"] == "Group A"
        return {
            "attempted": 1,
            "upserted": 1,
            "observed": 1,
            "discovered": 1,
            "entity_ids": ["entity-a"],
        }

    monkeypatch.setattr(server._writer, "prepare_context_for_persist", prepare_context)
    monkeypatch.setattr(server._entity_writer, "persist_items", persist_items)

    result = await server.process_payload(
        {
            "serial": "device-1",
            "strategy": "fb_groups",
            "xml": first,
            "xml_snapshots": [first, sparse_duplicate],
            "context": {"persist": True, "search_query": "group"},
        }
    )

    assert result["ok"] is True
