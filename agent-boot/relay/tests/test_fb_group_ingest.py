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


def _batch_items(result: dict) -> list[dict]:
    """Entities the agent handed to device_farm for persistence.

    The agent has no database, so what it parsed is only observable through the
    batch it ships back over the relay reply.
    """
    batch = result["persist_batch"]
    assert batch["kind"] == "entities"
    return batch["items"]


@pytest.mark.asyncio
async def test_process_payload_routes_fb_groups_to_entity_catalog() -> None:
    server = ExtraDataIngestServer()

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
    assert [item["display_name"] for item in _batch_items(result)] == ["OpenClaw VN"]
    assert result["items"][0]["display_name"] == "OpenClaw VN"
    # device_farm owns the write, so the agent reports no counts of its own.
    assert result["inserted_count"] == 0
    assert result["entity_ids"] == []


@pytest.mark.asyncio
async def test_process_payload_merges_all_group_crawl_snapshots_before_persist() -> None:
    server = ExtraDataIngestServer()
    first = _group_page(("Group A", 100), ("Group B", 200))
    second = _group_page(("Group B", 250), ("Group C", 300))

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

    batch_items = _batch_items(result)
    assert [item["display_name"] for item in batch_items] == [
        "Group A",
        "Group B",
        "Group C",
    ]
    assert batch_items[1]["metrics"]["member_count"] == 250


@pytest.mark.asyncio
async def test_group_snapshot_merge_keeps_richer_nested_fields() -> None:
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
    item = _batch_items(result)[0]
    assert item["metrics"]["member_count"] == 200
    assert item["attributes"]["privacy"] == "public"
    assert item["attributes"]["locator"]["search_query"] == "Group A"
