from __future__ import annotations

import pytest

from relay.extra_data.artifact_store import merge_evidence_into_item
from relay.extra_data.ingest import ExtraDataIngestServer, _build_post_id_map
from relay.extra_data.parent_resolve import resolve_fb_comment_parent_id
from relay.extra_data.writer import build_content_item_row, scope_content_hash


def test_merge_evidence_skips_hierarchy_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BOOT_INLINE_HIERARCHY_ENABLED", raising=False)
    item = {"text": "hello", "post_key": "p1"}
    xml = "<hierarchy><node text='hello' /></hierarchy>"
    merged = merge_evidence_into_item(
        item,
        {"hierarchy_xml": xml, "screenshot_path": "https://cdn/x.jpg"},
    )
    assert "hierarchy_xml" not in merged
    assert merged["_screenshot_path"] == "https://cdn/x.jpg"
    assert "hello" in merged["text"]


def test_merge_evidence_can_add_hierarchy_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BOOT_INLINE_HIERARCHY_ENABLED", "1")
    item = {"text": "hello", "post_key": "p1"}
    xml = "<hierarchy><node text='hello' /></hierarchy>"
    merged = merge_evidence_into_item(
        item,
        {"hierarchy_xml": xml, "screenshot_path": "https://cdn/x.jpg"},
    )
    assert merged["hierarchy_xml"] == xml
    assert merged["_screenshot_path"] == "https://cdn/x.jpg"
    assert "hello" in merged["text"]


def test_build_content_item_row_uses_image_desc_when_text_empty() -> None:
    row = build_content_item_row(
        {"post_key": "p1", "image_desc": "Ảnh nhóm AI", "author": "Test"},
        {"collection": "fb", "content_type": "fb_post", "hash_scope": "scope", "dedupe_field": "post_key"},
    )
    assert row["body"] == "Ảnh nhóm AI"


def test_build_post_id_map_uses_posts_dedupe_field() -> None:
    items = [{"_pid": "pid-1", "text": "Hello world", "post_key": "other-key"}]
    mapping = _build_post_id_map(
        items,
        {"dedupe_field": "post_key", "posts_dedupe_field": "text", "hash_scope": "exec-1"},
    )
    from relay.extra_data.writer import compute_content_hash, scope_content_hash

    expected = scope_content_hash(compute_content_hash(items[0], dedupe_field="text"), "exec-1")
    assert mapping["pid-1"] == expected


def test_resolve_parent_from_post_id_map() -> None:
    parent, scoped = resolve_fb_comment_parent_id(
        {
            "hash_scope": "exec-1",
            "_post_id_map": {"pid-abc": scope_content_hash("base", "exec-1")},
            "parent_post_id": "pid-abc",
        },
        [{"parent_post_id": "pid-abc", "text": "cmt"}],
    )
    assert scoped is True
    assert parent == scope_content_hash("base", "exec-1")


@pytest.mark.asyncio
async def test_process_payload_skips_hierarchy_raw_data_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BOOT_INLINE_HIERARCHY_ENABLED", raising=False)
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
    server._writer.lookup_parent_hash_for_post_pid = lambda **_: None  # type: ignore[method-assign]

    xml = "<hierarchy><node text='hello' /></hierarchy>"
    monkeypatch.setattr(
        "relay.extra_data.ingest._parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [{"post_key": "p1", "_pid": "pid-hello", "text": "hello", "platform": "facebook"}],
            {"reason_code": "ok"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "dev-1",
            "strategy": "fb_posts",
            "xml": xml,
            "evidence": {"hierarchy_xml": xml},
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
    assert "hierarchy_xml" not in inserted[0]["raw_data"]
    assert inserted[0]["screenshot_path"] is None
    assert "post_id_map" in result
    assert result["post_id_map"]
