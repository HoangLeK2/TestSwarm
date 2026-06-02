from __future__ import annotations

import pytest

from relay.extra_data.artifact_store import merge_evidence_into_item
from relay.extra_data.ingest import ExtraDataIngestServer
from relay.extra_data.writer import build_content_item_row


def test_merge_evidence_is_noop() -> None:
    item = {"text": "hello", "hierarchy_xml": "should-stay"}
    assert merge_evidence_into_item(item, {"hierarchy_xml": "<other/>", "screenshot_b64": "x"}) == item


def test_build_content_item_row_has_no_inline_hierarchy_by_default() -> None:
    row = build_content_item_row(
        {"text": "hello", "post_key": "p1"},
        {"collection": "fb", "content_type": "fb_post", "hash_scope": "scope", "dedupe_field": "post_key"},
    )
    assert "hierarchy_xml" not in (row.get("raw_data") or {})
    assert row["screenshot_path"] is None


@pytest.mark.asyncio
async def test_process_payload_does_not_emit_evidence_pending(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict] = []

    async def fake_insert(rows):
        inserted.extend(rows)
        return {
            "attempted": len(rows),
            "inserted": len(rows),
            "duplicates": 0,
            "inserted_content_hashes": [rows[0]["content_hash"]],
        }

    async def fake_prepare(ctx):
        return ctx

    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]
    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]

    monkeypatch.setattr(
        "relay.extra_data.ingest._parse_payload_items",
        lambda strategy, xml, context, payload: (
            [{"post_key": "p1", "text": "hello", "platform": "facebook"}],
            {"reason_code": "ok"},
            [xml],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "dev-1",
            "strategy": "fb_posts",
            "xml": "<hierarchy><node text='hello' /></hierarchy>",
            "context": {
                "persist": True,
                "collection": "fb_group_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "scope",
            },
        }
    )

    assert result["ok"] is True
    assert "evidence_pending" not in result
    assert inserted[0]["raw_data"] == {"post_key": "p1", "text": "hello", "platform": "facebook"}
    assert inserted[0]["screenshot_path"] is None
