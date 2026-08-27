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
async def test_process_payload_routes_fb_pages_to_entity_catalog() -> None:
    server = ExtraDataIngestServer()

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
    assert result["items"][0]["display_name"] == "Go2Joy Vietnam"
    # The agent has no database; what it parsed is observable only through the
    # batch it ships to device_farm for persistence.
    batch = result["persist_batch"]
    assert batch["kind"] == "entities"
    assert [(item["entity_type"], item["display_name"]) for item in batch["items"]] == [
        ("page", "Go2Joy Vietnam")
    ]
    # device_farm owns the write, so the agent reports no counts of its own.
    assert result["inserted_count"] == 0
    assert result["entity_ids"] == []
