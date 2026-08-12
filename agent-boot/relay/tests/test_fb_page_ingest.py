import pytest

from relay.extra_data.ingest import ExtraDataIngestServer
from relay.extra_data.parsers.facebook.page_pipeline import parse_page_search_results


def test_parse_page_search_results_extracts_page_cards() -> None:
    items, diagnostic = parse_page_search_results(
        '<hierarchy><node clickable="true" '
        'content-desc="Go2Joy Vietnam, Trang · 120K người thích · 130K người theo dõi" />'
        '<node clickable="true" content-desc="Trang" />'
        "</hierarchy>"
    )

    assert diagnostic["reason_code"] == "ok"
    assert diagnostic["pages_returned"] == 1
    assert items[0]["entity_type"] == "page"
    assert items[0]["display_name"] == "Go2Joy Vietnam"
    assert items[0]["metrics"] == {
        "like_count": 120_000,
        "follower_count": 130_000,
    }
    assert items[0]["attributes"]["locator"]["kind"] == "facebook_page_search_result"


@pytest.mark.asyncio
async def test_process_payload_routes_fb_pages_to_entity_catalog(monkeypatch) -> None:
    server = ExtraDataIngestServer()

    async def prepare_context(context):
        return {**context, "org_id": "org-a"}

    async def persist_items(items, *, context, captured_at=None):
        assert context["search_query"] == "go2joy"
        assert [(item["entity_type"], item["display_name"]) for item in items] == [
            ("page", "Go2Joy Vietnam")
        ]
        return {
            "attempted": 1,
            "upserted": 1,
            "observed": 1,
            "discovered": 1,
            "entity_ids": ["page-1"],
        }

    monkeypatch.setattr(server._writer, "prepare_context_for_persist", prepare_context)
    monkeypatch.setattr(server._entity_writer, "persist_items", persist_items)
    result = await server.process_payload(
        {
            "serial": "device-1",
            "strategy": "fb_pages",
            "xml": (
                '<hierarchy><node clickable="true" '
                'content-desc="Go2Joy Vietnam, Trang · 120K người thích" />'
                "</hierarchy>"
            ),
            "context": {
                "persist": True,
                "return_items": True,
                "search_query": "go2joy",
            },
        }
    )

    assert result["ok"] is True
    assert result["entity_ids"] == ["page-1"]
    assert result["observation_count"] == 1
    assert result["discovery_count"] == 1
    assert result["items"][0]["display_name"] == "Go2Joy Vietnam"
