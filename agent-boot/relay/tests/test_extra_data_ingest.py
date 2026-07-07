from __future__ import annotations

import sys
from typing import Any

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


def test_fb_comment_noise_filter_drops_empty_composer_placeholders() -> None:
    from relay.extra_data.parsers.facebook.filters import _is_comment_row_parse_noise

    assert _is_comment_row_parse_noise(
        {
            "author": "Chưa có bình luận nào",
            "text": "Hãy là người đầu tiên bình luận. Giúp tôi viết Thêm biểu tượng cảm xúc",
        }
    )
    assert _is_comment_row_parse_noise(
        {
            "author": "Giúp tôi viết",
            "text": "Thêm biểu tượng cảm xúc",
        }
    )


def test_fb_comment_target_returns_bounds_and_parent_hash(monkeypatch) -> None:
    class Module:
        pass

    module = Module()

    def fake_resolve(_xml, **_kwargs):
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


def test_fb_comment_target_uses_body_fallback_for_parent_anchor(monkeypatch) -> None:
    def fake_resolve(_xml, **_kwargs):
        top = {
            "post": {
                "_pid": "pid-1",
                "post_key": "post-1",
                "body": "body text from parsed post",
                "author": "Alice",
            },
            "comment_bounds": (10, 20, 110, 60),
        }
        return top, [top]

    import relay.extra_data.parsers.facebook as facebook

    monkeypatch.setattr(facebook, "resolve_comment_targets_from_xml", fake_resolve)
    _items, diagnostic = _parse_items(
        "fb_comment_target",
        "<hierarchy />",
        {"hash_scope": "scope", "dedupe_field": "post_key"},
    )

    assert diagnostic["target"]["pid"] == "pid-1"
    assert diagnostic["target"]["text_prefix"] == "body text from parsed post"


def test_fb_comment_target_reports_empty_when_no_candidate(monkeypatch) -> None:
    class Module:
        pass

    module = Module()
    module.resolve_comment_targets_from_xml = lambda _xml, **_kwargs: (None, [])
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
async def test_process_payload_strips_stale_campaign_before_insert(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            captured["before"] = dict(context)
            context["campaign_id"] = None
            context["execution_id"] = None
            return context

        async def insert_rows(self, rows):
            captured["rows"] = rows
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()
    xml = '<hierarchy><node text="Hello" /></hierarchy>'

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "text_nodes",
        "xml": xml,
        "context": {
            "persist": True,
            "collection": "fb_posts",
            "campaign_id": "missing-campaign",
            "execution_id": "missing-exec",
        },
    })

    assert result["ok"] is True
    assert result["inserted_count"] == 1
    assert captured["before"]["campaign_id"] == "missing-campaign"
    assert captured["rows"][0]["campaign_id"] is None


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
async def test_process_payload_returns_single_fb_post_as_active_parent(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict[str, Any]] = []

    async def fake_prepare(ctx):
        return ctx

    async def fake_insert(rows):
        inserted.extend(rows)
        return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]
    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [
                {
                    "_pid": "pid-1",
                    "post_key": "post-1",
                    "stable_post_id": "stable-1",
                    "fb_post_id": "fb-1",
                    "author": "Alice",
                    "timestamp": "1 giờ",
                    "text": "parent post body",
                }
            ],
            {"reason_code": "ok"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="post" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
            },
        }
    )

    assert result["ok"] is True
    assert inserted
    assert result["active_parent_post"] == {
        "pid": "pid-1",
        "parent_id": inserted[0]["content_hash"],
        "post_key": "post-1",
        "stable_post_id": "stable-1",
        "fb_post_id": "fb-1",
        "author": "Alice",
        "timestamp": "1 giờ",
        "text_prefix": "parent post body",
    }


@pytest.mark.asyncio
async def test_process_payload_does_not_return_active_parent_for_multiple_fb_posts(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict[str, Any]] = []

    async def fake_prepare(ctx):
        return ctx

    async def fake_insert(rows):
        inserted.extend(rows)
        return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]
    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [
                {"_pid": "pid-1", "post_key": "post-1", "text": "first post"},
                {"_pid": "pid-2", "post_key": "post-2", "text": "second post"},
            ],
            {"reason_code": "ok"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="posts" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
            },
        }
    )

    assert result["ok"] is True
    assert len(inserted) == 2
    assert "active_parent_post" not in result
    assert result["post_id_map"] == {
        "pid-1": inserted[0]["content_hash"],
        "pid-2": inserted[1]["content_hash"],
    }


@pytest.mark.asyncio
async def test_process_payload_post_detail_uses_first_post_when_diagnostic_missing(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict[str, Any]] = []

    async def fake_prepare(ctx):
        return ctx

    async def fake_insert(rows):
        inserted.extend(rows)
        return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]
    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [
                {"_pid": "pid-detail", "post_key": "post-detail", "text": "opened detail post"},
                {"_pid": "pid-noise", "post_key": "post-noise", "text": "detail chrome noise"},
            ],
            {"reason_code": "ok"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="post detail" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
                "open_post_detail": True,
            },
        }
    )

    assert result["ok"] is True
    assert len(inserted) == 2
    assert result["active_parent_post"]["parent_id"] == inserted[0]["content_hash"]
    assert result["active_parent_post"]["pid"] == "pid-detail"
    assert result["active_parent_post"]["source"] == "post_detail"
    assert result["active_parent_post"]["selection_reason"] == "post_detail_first_parsed"


@pytest.mark.asyncio
async def test_process_payload_uses_opened_post_diagnostic_to_pick_active_parent(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict[str, Any]] = []

    async def fake_prepare(ctx):
        return ctx

    async def fake_insert(rows):
        inserted.extend(rows)
        return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]
    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [
                {"_pid": "pid-1", "post_key": "post-1", "text": "wrong nearby post"},
                {"_pid": "pid-2", "post_key": "post-2", "text": "opened post body"},
            ],
            {"reason_code": "ok"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="posts" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
                "open_post_detail": True,
                "open_post_detail_diagnostic": {
                    "reason_code": "ok",
                    "opened_post": {
                        "pid": "pid-2",
                        "post_key": "post-2",
                        "author": "Alice",
                        "text_prefix": "opened post body from feed",
                    },
                },
            },
        }
    )

    assert result["ok"] is True
    assert len(inserted) == 2
    assert result["active_parent_post"] == {
        "pid": "pid-2",
        "parent_id": inserted[1]["content_hash"],
        "post_key": "post-2",
        "author": "Alice",
        "text_prefix": "opened post body",
        "source": "post_detail",
    }


@pytest.mark.asyncio
async def test_process_payload_persists_opened_post_parent_when_comment_sheet_has_no_post_rows(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict[str, Any]] = []

    async def fake_prepare(ctx):
        return ctx

    async def fake_insert(rows):
        inserted.extend(rows)
        return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]
    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [],
            {"reason_code": "no_post_rows"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="comment sheet" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
                "open_post_detail": True,
                "open_post_detail_diagnostic": {
                    "reason_code": "comment_sheet",
                    "opened_post": {
                        "pid": "pid-comment-sheet",
                        "post_key": "post-comment-sheet",
                        "author": "Alice",
                        "timestamp": "5 phút",
                        "text_prefix": "opened post body before comment sheet",
                    },
                },
            },
        }
    )

    assert result["ok"] is True
    assert len(inserted) == 1
    assert inserted[0]["raw_data"]["post_key"] == "post-comment-sheet"
    assert inserted[0]["body"] == "opened post body before comment sheet"
    assert result["diagnostic"]["opened_post_synthetic_parent"] is True
    assert result["active_parent_post"]["parent_id"] == inserted[0]["content_hash"]
    assert result["active_parent_post"]["pid"] == "pid-comment-sheet"
    assert result["active_parent_post"]["source"] == "post_detail"


@pytest.mark.asyncio
async def test_process_payload_marks_post_detail_active_parent_source(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict[str, Any]] = []

    async def fake_prepare(ctx):
        return ctx

    async def fake_insert(rows):
        inserted.extend(rows)
        return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]
    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [{"_pid": "pid-detail", "post_key": "post-detail", "text": "opened detail post"}],
            {"reason_code": "ok"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="post detail" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
                "open_post_detail": True,
            },
        }
    )

    assert result["ok"] is True
    assert result["active_parent_post"]["parent_id"] == inserted[0]["content_hash"]
    assert result["active_parent_post"]["source"] == "post_detail"


@pytest.mark.asyncio
async def test_process_payload_matches_opened_post_by_text_when_ids_differ(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict[str, Any]] = []

    async def fake_prepare(ctx):
        return ctx

    async def fake_insert(rows):
        inserted.extend(rows)
        return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]
    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [
                {
                    "_pid": "detail-generated-1",
                    "post_key": "detail-post-1",
                    "author": "Bob",
                    "text": "wrong nearby post body",
                },
                {
                    "_pid": "detail-generated-2",
                    "post_key": "detail-post-2",
                    "author": "Alice",
                    "timestamp": "5 ngày",
                    "text": "opened post body after detail parser recomputed id",
                },
            ],
            {"reason_code": "ok"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="posts" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
                "open_post_detail": True,
                "open_post_detail_diagnostic": {
                    "reason_code": "ok",
                    "opened_post": {
                        "pid": "feed-pid",
                        "post_key": "feed-post-key",
                        "author": "Alice",
                        "timestamp": "5 ngày",
                        "text_prefix": "opened post body after detail parser",
                    },
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["active_parent_post"]["parent_id"] == inserted[1]["content_hash"]
    assert result["active_parent_post"]["pid"] == "detail-generated-2"
    assert result["active_parent_post"]["author"] == "Alice"


@pytest.mark.asyncio
async def test_process_payload_active_parent_uses_image_desc_text_fallback(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    inserted: list[dict[str, Any]] = []

    async def fake_prepare(ctx):
        return ctx

    async def fake_insert(rows):
        inserted.extend(rows)
        return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server._writer.prepare_context_for_persist = fake_prepare  # type: ignore[method-assign]
    server._writer.insert_rows = fake_insert  # type: ignore[method-assign]

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_payload_items",
        lambda strategy, xml_in, context, payload: (
            [
                {
                    "_pid": "pid-image",
                    "post_key": "post-image",
                    "author": "Alice",
                    "image_desc": "image-only parent post",
                }
            ],
            {"reason_code": "ok"},
            [xml_in],
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="image post" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
            },
        }
    )

    assert result["ok"] is True
    assert result["active_parent_post"]["parent_id"] == inserted[0]["content_hash"]
    assert result["active_parent_post"]["pid"] == "pid-image"
    assert result["active_parent_post"]["text_prefix"] == "image-only parent post"


def test_merge_fb_comment_frames_dedupes_and_keeps_latest_stats() -> None:
    items, diagnostic = extra_data_ingest.merge_fb_comment_frames(
        [
            (
                [
                    {"_type": "post_stats", "comment_count": 1},
                    {"comment_key": "c1", "text": "first"},
                ],
                {"reason_code": "ok"},
            ),
            (
                [
                    {"_type": "post_stats", "comment_count": 2},
                    {"comment_key": "c1", "text": "duplicate"},
                    {"comment_key": "c2", "text": "second"},
                    {"comment_key": "c3", "text": "third"},
                ],
                {"reason_code": "ok"},
            ),
        ],
        max_items=2,
    )

    assert items == [
        {"_type": "post_stats", "comment_count": 2},
        {"comment_key": "c1", "text": "first"},
        {"comment_key": "c2", "text": "second"},
    ]
    assert diagnostic["snapshot_count"] == 2
    assert diagnostic["frame_reason_codes"] == ["ok", "ok"]
    assert diagnostic["comments_returned"] == 2
    assert diagnostic["has_header_stats"] is True


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


@pytest.mark.asyncio
async def test_process_payload_uses_trusted_preparsed_fb_comments(monkeypatch) -> None:
    def fail_parse(*args, **kwargs):
        raise AssertionError("preparsed path should not parse XML")

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fail_parse)

    class FakeWriter:
        async def insert_rows(self, rows):
            raise AssertionError("persist disabled")

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()
    xml = '<hierarchy><node text="evidence" /></hierarchy>'

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "fb_comments",
        "xml": xml,
        "context": {
            "persist": False,
            "return_items": True,
            "agent_boot_preparsed_comments": True,
            "parent_id": "parent-1",
            "require_verified_parent": False,
        },
        "preparsed": {
            "items": [{"comment_key": "c1", "text": "first"}],
            "diagnostic": {"reason_code": "ok", "comments_returned": 1},
            "snapshot_count": 3,
            "xml_bytes": 12345,
        },
    })

    assert result["ok"] is True
    assert result["snapshot_count"] == 3
    assert result["payload_snapshot_count"] == 1
    assert result["xml_bytes"] == 12345
    assert result["payload_xml_bytes"] == len(xml.encode("utf-8"))
    assert result["diagnostic"]["preparsed"] is True
    assert result["items"][0]["comment_key"] == "c1"
    assert result["items"][0]["parent_content_hash"] == "parent-1"


@pytest.mark.asyncio
async def test_process_payload_persists_fb_comment_post_stats_to_parent(monkeypatch) -> None:
    def fail_parse(*args, **kwargs):
        raise AssertionError("preparsed path should not parse XML")

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fail_parse)

    class FakeWriter:
        def __init__(self) -> None:
            self.rows = []
            self.update_calls = []

        async def prepare_context_for_persist(self, context):
            return context

        async def insert_rows(self, rows):
            self.rows = rows
            return {
                "attempted": len(rows),
                "inserted": len(rows),
                "duplicates": 0,
                "inserted_content_hashes": [row["content_hash"] for row in rows],
            }

        async def update_content_stats(self, **kwargs):
            self.update_calls.append(kwargs)
            return True

    writer = FakeWriter()
    server = ExtraDataIngestServer()
    server._writer = writer
    xml = '<hierarchy><node text="evidence" /></hierarchy>'

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "fb_comments",
        "xml": xml,
        "context": {
            "collection": "fb",
            "persist": True,
            "return_items": True,
            "agent_boot_preparsed_comments": True,
            "parent_id": "parent-scoped-hash",
            "parent_id_already_scoped": True,
            "require_verified_parent": False,
        },
        "preparsed": {
            "items": [
                {"_type": "post_stats", "reactions": "12", "comments": "10", "shares": "2"},
                {"comment_key": "c1", "text": "first"},
            ],
            "diagnostic": {"reason_code": "ok", "comments_returned": 1},
        },
    })

    assert result["ok"] is True
    assert result["parsed_count"] == 2
    assert result["inserted_count"] == 1
    assert len(writer.rows) == 1
    assert writer.update_calls == [
        {
            "content_hash": "parent-scoped-hash",
            "likes_count": "12",
            "comments_count": "10",
            "shares_count": "2",
        }
    ]
    assert result["diagnostic"]["post_stats_found"] is True
    assert result["diagnostic"]["post_stats_persisted"] is True
    assert result["items"] == [
        {
            "comment_key": "c1",
            "text": "first",
            "parent_content_hash": "parent-scoped-hash",
        }
    ]


@pytest.mark.asyncio
async def test_process_payload_invalid_preparsed_fb_comments_falls_back(monkeypatch) -> None:
    class Module:
        pass

    module = Module()
    called = {"count": 0}

    def fake_parse(xml, parent_post_id=None, max_items=50):
        called["count"] += 1
        return [{"comment_key": "c1", "text": "from-xml"}], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    class FakeWriter:
        async def insert_rows(self, rows):
            raise AssertionError("persist disabled")

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "fb_comments",
        "xml": '<hierarchy><node text="frame-1" /></hierarchy>',
        "context": {
            "persist": False,
            "return_items": True,
            "agent_boot_preparsed_comments": True,
        },
        "preparsed": {"items": "invalid"},
    })

    assert result["ok"] is True
    assert called["count"] == 1
    assert result["diagnostic"].get("preparsed") is None
    assert result["items"][0]["text"] == "from-xml"


@pytest.mark.asyncio
async def test_process_payload_adds_parent_context_to_fb_comment_rows(monkeypatch) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [{"comment_key": "c1", "text": "comment body", "author": "Bob"}], {
            "reason_code": "ok"
        }

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    inserted: list[dict[str, Any]] = []

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def insert_rows(self, rows):
            inserted.extend(rows)
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()
    xml = '<hierarchy><node text="comments" /></hierarchy>'

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": xml,
            "context": {
                "persist": True,
                "collection": "fb_comments",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
                "parent_id": "scoped-parent-hash",
                "parent_id_already_scoped": True,
                "parent_post_id": "pid-parent",
                "_active_comment_parent_anchor": {
                    "author": "Alice",
                    "timestamp": "1 giờ",
                    "text_prefix": "parent post text",
                },
            },
        }
    )

    assert result["ok"] is True
    assert inserted[0]["parent_id"] == "scoped-parent-hash"
    assert inserted[0]["raw_data"]["parent_post_id"] == "pid-parent"
    assert inserted[0]["raw_data"]["parent_content_hash"] == "scoped-parent-hash"
    assert inserted[0]["raw_data"]["parent_post_anchor"] == {
        "author": "Alice",
        "timestamp": "1 giờ",
        "text_prefix": "parent post text",
    }


@pytest.mark.asyncio
async def test_process_payload_replaces_stale_comment_parent_hash_when_parser_pid_differs(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [
            {
                "comment_key": "c1",
                "text": "comment body",
                "author": "Bob",
                "parent_post_id": "pid-current",
            }
        ], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    inserted: list[dict[str, Any]] = []

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def insert_rows(self, rows):
            inserted.extend(rows)
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_comments",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
                "parent_id": "stale-parent-hash",
                "parent_id_already_scoped": True,
                "parent_post_id": "pid-stale",
                "_post_id_map": {"pid-current": "current-parent-hash"},
                "_active_comment_parent_anchor": {
                    "pid": "pid-stale",
                    "text_prefix": "stale parent text",
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["diagnostic"]["parent_context_corrected"] is True
    assert result["diagnostic"]["context_parent_post_id"] == "pid-stale"
    assert result["diagnostic"]["parsed_parent_post_ids"] == ["pid-current"]
    assert inserted[0]["parent_id"] == "current-parent-hash"
    assert inserted[0]["raw_data"]["parent_post_id"] == "pid-current"
    assert inserted[0]["raw_data"]["parent_content_hash"] == "current-parent-hash"
    assert "parent_post_anchor" not in inserted[0]["raw_data"]


@pytest.mark.asyncio
async def test_process_payload_keeps_post_detail_parent_when_comment_parser_pid_differs(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [
            {
                "comment_key": "c1",
                "text": "comment body",
                "author": "Bob",
                "parent_post_id": "sheet-generated-pid",
            }
        ], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    inserted: list[dict[str, Any]] = []

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def lookup_parent_hash_for_post_pid(self, **kwargs):
            raise AssertionError("post-detail parent must not be re-resolved by parser pid")

        async def insert_rows(self, rows):
            inserted.extend(rows)
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_comments",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
                "parent_id": "detail-parent-hash",
                "parent_id_already_scoped": True,
                "parent_post_id": "detail-pid",
                "parent_context_source": "post_detail",
                "_active_comment_parent_anchor": {
                    "pid": "detail-pid",
                    "text_prefix": "opened detail post",
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["diagnostic"]["parent_context_locked"] is True
    assert result["diagnostic"]["parsed_parent_post_ids"] == ["sheet-generated-pid"]
    assert inserted[0]["parent_id"] == "detail-parent-hash"
    assert inserted[0]["raw_data"]["parent_post_id"] == "detail-pid"
    assert inserted[0]["raw_data"]["parser_parent_post_id"] == "sheet-generated-pid"
    assert inserted[0]["raw_data"]["parent_content_hash"] == "detail-parent-hash"
    assert inserted[0]["raw_data"]["parent_context_source"] == "post_detail"


@pytest.mark.asyncio
async def test_process_payload_keeps_verified_tap_parent_when_comment_parser_pid_differs(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [
            {
                "comment_key": "c1",
                "text": "comment body",
                "author": "Bob",
                "parent_post_id": "sheet-generated-pid",
            }
        ], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    inserted: list[dict[str, Any]] = []

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def lookup_parent_hash_for_post_pid(self, **kwargs):
            raise AssertionError("verified tap parent must not be re-resolved by parser pid")

        async def insert_rows(self, rows):
            inserted.extend(rows)
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_comments",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
                "parent_id": "tap-parent-hash",
                "parent_id_already_scoped": True,
                "parent_post_id": "tap-pid",
                "parent_context_source": "tap_fb_comment_button",
                "_active_comment_parent_anchor": {
                    "pid": "tap-pid",
                    "text_prefix": "verified feed post",
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["diagnostic"]["parent_context_locked"] is True
    assert result["diagnostic"]["parsed_parent_post_ids"] == ["sheet-generated-pid"]
    assert inserted[0]["parent_id"] == "tap-parent-hash"
    assert inserted[0]["raw_data"]["parent_post_id"] == "tap-pid"
    assert inserted[0]["raw_data"]["parser_parent_post_id"] == "sheet-generated-pid"
    assert inserted[0]["raw_data"]["parent_content_hash"] == "tap-parent-hash"
    assert inserted[0]["raw_data"]["parent_context_source"] == "tap_fb_comment_button"


@pytest.mark.asyncio
async def test_process_payload_preserves_parser_parent_post_id_without_context(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [{"comment_key": "c1", "text": "comment body", "parent_post_id": "pid-from-parser"}], {
            "reason_code": "ok"
        }

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    inserted: list[dict[str, Any]] = []

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def lookup_parent_hash_for_post_pid(self, **kwargs):
            return None

        async def insert_rows(self, rows):
            inserted.extend(rows)
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_comments",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
            },
        }
    )

    assert result["ok"] is True
    assert inserted[0]["raw_data"]["parent_post_id"] == "pid-from-parser"


@pytest.mark.asyncio
async def test_process_payload_requires_verified_parent_before_persisting_comments(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [{"comment_key": "c1", "text": "comment body", "parent_post_id": "pid-from-parser"}], {
            "reason_code": "ok"
        }

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def lookup_parent_hash_for_post_pid(self, **kwargs):
            return "looked-up-parent-hash"

        async def insert_rows(self, rows):
            raise AssertionError("unverified parent comments must not be persisted")

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_comments",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
                "require_verified_parent": True,
            },
        }
    )

    assert result["ok"] is True
    assert result["parsed_count"] == 1
    assert result["inserted_attempted"] == 0
    assert result["inserted_count"] == 0
    assert result["diagnostic"]["parent_context_required"] is True
    assert result["diagnostic"]["parent_context_missing"] is True


@pytest.mark.asyncio
async def test_process_payload_requires_verified_parent_by_default_for_fb_group_posts(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [{"comment_key": "c1", "text": "comment body", "parent_post_id": "pid-from-parser"}], {
            "reason_code": "ok"
        }

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def lookup_parent_hash_for_post_pid(self, **kwargs):
            return "looked-up-parent-hash"

        async def insert_rows(self, rows):
            raise AssertionError("fb_group_posts comments need verified parent context")

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_group_posts",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
            },
        }
    )

    assert result["ok"] is True
    assert result["parsed_count"] == 1
    assert result["inserted_attempted"] == 0
    assert result["diagnostic"]["parent_context_required"] is True
    assert result["diagnostic"]["parent_context_missing"] is True


@pytest.mark.asyncio
async def test_process_payload_uses_latest_post_parent_when_step_context_was_lost(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [
            {
                "comment_key": "c1",
                "text": "comment body",
                "author": "Bob",
                "parent_post_id": "parser-generated-pid",
            }
        ], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    inserted: list[dict[str, Any]] = []
    latest_lookup: dict[str, Any] = {}

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def lookup_parent_hash_for_post_pid(self, **kwargs):
            return None

        async def lookup_latest_parent_hash_for_context(self, **kwargs):
            latest_lookup.update(kwargs)
            return "latest-post-hash"

        async def insert_rows(self, rows):
            inserted.extend(rows)
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_group_posts",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
                "execution_id": "exec-1",
            },
        }
    )

    assert result["ok"] is True
    assert result["inserted_count"] == 1
    assert result["diagnostic"]["parent_context_latest_post_fallback"] is True
    assert result["diagnostic"]["latest_parent_hash"] == "latest-post-hash"
    assert latest_lookup == {
        "collection": "fb_group_posts",
        "execution_id": "exec-1",
        "device_serial": "serial-1",
    }
    assert inserted[0]["parent_id"] == "latest-post-hash"
    assert inserted[0]["raw_data"]["parent_content_hash"] == "latest-post-hash"
    assert inserted[0]["raw_data"]["parent_context_source"] == "latest_post_in_execution"


@pytest.mark.asyncio
async def test_process_payload_relinks_verified_parent_to_persisted_post_hash(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [
            {
                "comment_key": "c1",
                "text": "comment body",
                "author": "Bob",
                "parent_post_id": "parser-generated-pid",
            }
        ], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    inserted: list[dict[str, Any]] = []

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def lookup_parent_hash_for_post_pid(self, **kwargs):
            assert kwargs["parent_post_id"] == "verified-pid"
            return "persisted-post-hash"

        async def insert_rows(self, rows):
            inserted.extend(rows)
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_comments",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
                "parent_id": "tap-target-orphan-hash",
                "parent_id_already_scoped": True,
                "parent_post_id": "verified-pid",
                "parent_context_source": "tap_fb_comment_button",
                "require_verified_parent": True,
                "_active_comment_parent_anchor": {
                    "pid": "verified-pid",
                    "text_prefix": "verified parent post",
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["diagnostic"]["parent_context_relinked"] is True
    assert result["diagnostic"]["context_parent_hash"] == "tap-target-orphan-hash"
    assert result["diagnostic"]["canonical_parent_hash"] == "persisted-post-hash"
    assert inserted[0]["parent_id"] == "persisted-post-hash"
    assert inserted[0]["raw_data"]["parent_post_id"] == "verified-pid"
    assert inserted[0]["raw_data"]["parser_parent_post_id"] == "parser-generated-pid"
    assert inserted[0]["raw_data"]["parent_content_hash"] == "persisted-post-hash"


@pytest.mark.asyncio
async def test_process_payload_persists_comments_when_pid_lookup_misses_scoped_parent(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [
            {
                "comment_key": "c1",
                "text": "comment body",
                "author": "Bob",
                "parent_post_id": "parser-generated-pid",
            }
        ], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)

    inserted: list[dict[str, Any]] = []

    class FakeWriter:
        async def prepare_context_for_persist(self, context):
            return context

        async def lookup_parent_hash_for_post_pid(self, **kwargs):
            return None

        async def insert_rows(self, rows):
            inserted.extend(rows)
            return {"attempted": len(rows), "inserted": len(rows), "duplicates": 0}

    server = ExtraDataIngestServer()
    server._writer = FakeWriter()

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": '<hierarchy><node text="comments" /></hierarchy>',
            "context": {
                "persist": True,
                "collection": "fb_group_posts",
                "content_type": "fb_comment",
                "dedupe_field": "comment_key",
                "hash_scope": "exec-1",
                "execution_id": "exec-1",
                "parent_id": "scoped-parent-from-posts",
                "parent_id_already_scoped": True,
                "parent_post_id": "pid-from-posts",
                "parent_context_source": "post_detail",
                "require_verified_parent": True,
            },
        }
    )

    assert result["ok"] is True
    assert result["inserted_count"] == 1
    assert result["diagnostic"]["parent_lookup_fallback"] is True
    assert inserted[0]["parent_id"] == "scoped-parent-from-posts"
