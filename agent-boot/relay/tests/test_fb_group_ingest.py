import pytest

from relay.extra_data.ingest import ExtraDataIngestServer


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
