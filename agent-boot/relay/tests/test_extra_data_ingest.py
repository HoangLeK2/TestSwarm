from __future__ import annotations

import sys

import pytest

from relay.extra_data import ingest as extra_data_ingest
from relay.extra_data.ingest import ExtraDataIngestServer, _parse_items


def test_fb_comments_parser_accepts_parent_id_context(monkeypatch) -> None:
    captured = {}
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        captured["xml"] = xml
        captured["parent_post_id"] = parent_post_id
        captured["max_items"] = max_items
        return [{"comment_key": "c1", "text": "hello"}], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    items, diagnostic = _parse_items(
        "fb_comments",
        "<hierarchy />",
        {"parent_id": "parent-hash", "max_items": 7},
    )

    assert items == [{"comment_key": "c1", "text": "hello"}]
    assert diagnostic == {"reason_code": "ok"}
    assert captured == {
        "xml": "<hierarchy />",
        "parent_post_id": "parent-hash",
        "max_items": 7,
    }


def test_facebook_parser_diagnostic_module_imports() -> None:
    from relay.extra_data.parsers.facebook import diagnostic

    assert callable(diagnostic.parse_fb_posts_from_xml_with_diagnostic)
    assert callable(diagnostic.parse_fb_comments_from_xml_with_diagnostic)


def test_fb_comment_target_returns_bounds_and_parent_hash(monkeypatch) -> None:
    class Module:
        pass

    module = Module()

    def fake_resolve(_xml):
        top = {
            "post": {"_pid": "pid-1", "post_key": "post-1", "text": "hello", "author": "Alice"},
            "comment_bounds": (10, 20, 110, 60),
            "parent_post_bounds": (0, 100, 1080, 800),
            "score": 0.12,
            "breakdown": {"distance": 0.1, "cut_penalty": 0.0},
            "feed_item_index": 0,
        }
        alt = {
            "post": {"_pid": "pid-2", "post_key": "post-2", "text": "world", "author": "Bob"},
            "comment_bounds": (10, 1400, 110, 1440),
            "parent_post_bounds": None,
            "score": 0.34,
            "breakdown": {"distance": 0.3, "cut_penalty": 0.04},
            "feed_item_index": 1,
        }
        return top, [top, alt]

    module.resolve_comment_targets_from_xml = fake_resolve
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    items, diagnostic = _parse_items(
        "fb_comment_target_tap",
        "<hierarchy />",
        {"hash_scope": "scope", "dedupe_field": "post_key"},
    )

    assert items == []
    assert diagnostic["reason_code"] == "ok"
    assert diagnostic["target"]["bounds"] == [10, 20, 110, 60]
    assert diagnostic["target"]["pid"] == "pid-1"
    assert diagnostic["target"]["parent_base_hash"]
    assert diagnostic["target"]["parent_id"] != diagnostic["target"]["parent_base_hash"]
    assert diagnostic["target"]["score"] == 0.12
    assert diagnostic["target"]["score_breakdown"]["distance"] == 0.1
    assert diagnostic["target"]["parent_post_bounds"] == [0, 100, 1080, 800]
    assert diagnostic["candidate_count"] == 2
    assert len(diagnostic["alternates"]) == 1
    assert diagnostic["alternates"][0]["bounds"] == [10, 1400, 110, 1440]
    assert diagnostic["alternates"][0]["pid"] == "pid-2"


def test_fb_comment_target_reports_empty_when_no_candidate(monkeypatch) -> None:
    class Module:
        pass

    module = Module()
    module.resolve_comment_targets_from_xml = lambda _xml: (None, [])
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    items, diagnostic = _parse_items("fb_comment_target", "<hierarchy />", {})

    assert items == []
    assert diagnostic["reason_code"] == "comment_button_not_found"
    assert diagnostic["target"] is None
    assert diagnostic["alternates"] == []
    assert diagnostic["candidate_count"] == 0


def test_text_nodes_parser_lives_in_agent_boot() -> None:
    items, diagnostic = _parse_items(
        "text_nodes",
        '<hierarchy><node text="Hello" /><node text="World" /></hierarchy>',
        {},
    )

    assert [item["text"] for item in items] == ["Hello", "World"]
    assert diagnostic == {"reason_code": "ok", "texts_returned": 2}


def test_tiktok_posts_parser_lives_in_agent_boot() -> None:
    xml = (
        '<hierarchy package="com.zhiliaoapp.musically">'
        '<node content-desc="Alice, demo video, 1.2K likes, 45 comments, 3M views" />'
        "</hierarchy>"
    )

    items, diagnostic = _parse_items("tiktok_posts", xml, {})

    assert diagnostic["reason_code"] == "ok"
    assert diagnostic["platform"] == "tiktok"
    assert len(items) == 1
    assert items[0]["platform"] == "tiktok"
    assert items[0]["content_type"] == "video"
    assert items[0]["likes_count"] == 1200


def test_extra_data_ingest_requires_token_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BOOT_EXTRA_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_BOOT_EXTRA_ALLOW_UNAUTH", raising=False)
    server = ExtraDataIngestServer()

    assert server._authorize({}, {}) == (503, "extra_token_not_configured")


def test_extra_data_ingest_authorizes_configured_token(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BOOT_EXTRA_TOKEN", "secret")
    server = ExtraDataIngestServer()

    assert server._authorize({"x-agent-boot-extra-token": "secret"}, {}) is None
    assert server._authorize({"x-agent-boot-extra-token": "wrong"}, {}) == (401, "unauthorized")


@pytest.mark.asyncio
async def test_insert_rows_retries_transient_db_error(monkeypatch) -> None:
    class FakeWriter:
        def __init__(self) -> None:
            self.calls = 0

        async def insert_rows(self, rows):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary db outage")
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    async def no_sleep(_delay):
        return None

    monkeypatch.setenv("AGENT_BOOT_CONTENT_DB_RETRIES", "2")
    monkeypatch.setattr(extra_data_ingest.asyncio, "sleep", no_sleep)
    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server._insert_rows_with_retry([{"id": "1"}])

    assert result == {"attempted": 1, "inserted": 1, "duplicates": 0}
    assert server._writer.calls == 2


@pytest.mark.asyncio
async def test_process_payload_can_return_items_without_persist(monkeypatch) -> None:
    class FakeWriter:
        def __init__(self) -> None:
            self.calls = 0

        async def insert_rows(self, rows):
            self.calls += 1
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    writer = FakeWriter()
    server._writer = writer
    xml = '<hierarchy><node text="Hello" /></hierarchy>'

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "text_nodes",
        "xml": xml,
        "context": {"persist": False, "return_items": True},
    })

    assert result["ok"] is True
    assert result["inserted_count"] == 0
    assert writer.calls == 0
    assert result["items"] == [{"text": "Hello", "body": "Hello", "content_type": "text"}]


@pytest.mark.asyncio
async def test_process_payload_merges_fb_comment_snapshots(monkeypatch) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        if "frame-2" in xml:
            return [
                {"comment_key": "c1", "text": "duplicate"},
                {"comment_key": "c2", "text": "second"},
            ], {"reason_code": "ok"}
        return [{"comment_key": "c1", "text": "first"}], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    class FakeWriter:
        async def insert_rows(self, rows):
            raise AssertionError("persist disabled")

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()
    xml1 = '<hierarchy><node text="frame-1" /></hierarchy>'
    xml2 = '<hierarchy><node text="frame-2" /></hierarchy>'

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "fb_comments",
        "xml": xml1,
        "xml_snapshots": [xml1, xml2],
        "context": {"persist": False, "return_items": True, "max_items": 10},
    })

    assert result["ok"] is True
    assert result["snapshot_count"] == 2
    assert result["parsed_count"] == 2
    assert result["diagnostic"]["comments_returned"] == 2
    assert [item["comment_key"] for item in result["items"]] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_process_payload_merges_fb_comments_respects_high_max_items_default(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()
    captured_max: list[int] = []

    def fake_parse(xml, parent_post_id=None, max_items=50):
        captured_max.append(max_items)
        idx = len(captured_max)
        return [{"comment_key": f"c{idx}", "text": f"frame-{idx}"}], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    class FakeWriter:
        async def insert_rows(self, rows):
            raise AssertionError("persist disabled")

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()
    xml1 = '<hierarchy><node text="frame-1" /></hierarchy>'
    xml2 = '<hierarchy><node text="frame-2" /></hierarchy>'

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "fb_comments",
        "xml": xml1,
        "xml_snapshots": [xml1, xml2],
        "context": {"persist": False, "return_items": True},
    })

    assert result["ok"] is True
    assert result["parsed_count"] == 2
    assert captured_max == [400, 400]
