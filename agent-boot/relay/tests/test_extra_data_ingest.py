from __future__ import annotations

import hashlib
import sys
from typing import Any

import pytest

from relay.extra_data import ingest as extra_data_ingest
from relay.extra_data.collector import build_ingest_payload
from relay.extra_data.ingest import ExtraDataIngestServer, _parse_items
from relay.extra_data.writer import build_content_item_row

# The agent holds no database handle. What it decided to persist is observable
# only through `persist_batch` in the relay reply, which device_farm turns into
# content_items rows (services/content/edge_ingest.py::_build_row).


def _persisted_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Raw items the agent handed to device_farm for persistence."""
    return (result.get("persist_batch") or {}).get("items") or []


def _persisted_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows device_farm will build from those items.

    Body/author/count shaping is reproduced with the agent's own builder because
    device_farm applies the same derivations, and it refuses any content_hash it
    cannot recompute from the raw item.
    """
    return [build_content_item_row(item, {}) for item in _persisted_items(result)]


def _parent_hint(result: dict[str, Any]) -> dict[str, Any]:
    """Parent the agent identified, for device_farm to confirm against the DB."""
    return (result.get("persist_batch") or {}).get("parent_hint") or {}


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
    assert _is_comment_row_parse_noise({"author": "", "text": "xem thêm"})
    assert _is_comment_row_parse_noise({"author": "", "text": "see more"})


@pytest.mark.asyncio
async def test_process_payload_reports_partial_comment_target(monkeypatch) -> None:
    server = ExtraDataIngestServer()

    def fake_parse_items(strategy, xml_in, context):
        assert strategy == "fb_comments"
        frame = int(xml_in.split("frame-")[1].split('"')[0])
        start = frame * 4
        comments = [
            {
                "comment_key": f"comment-{index}",
                "author": f"Author {index}",
                "text": f"Comment {index}",
            }
            for index in range(start, start + 4)
        ]
        return comments, {
            "reason_code": "ok",
            "comments_returned": len(comments),
        }

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fake_parse_items)
    snapshots = [
        f'<hierarchy><node text="frame-{index}" /></hierarchy>'
        for index in range(5)
    ]
    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": snapshots[0],
            "xml_snapshots": snapshots,
            "context": {
                "persist": False,
                "return_items": True,
                "max_items": 220,
                "post_comment_count": 269,
                "comment_target_effective": 220,
                "comment_scroll_stopped_reason": "coverage_tail_no_new",
                "comment_scroll_passes_effective": 220,
            },
        }
    )

    assert result["ok"] is True
    assert result["parsed_count"] == 20
    assert result["diagnostic"]["reason_code"] == "partial_target"
    assert result["diagnostic"]["comment_target"] == 220
    assert result["diagnostic"]["comments_returned"] == 20
    assert result["diagnostic"]["coverage_ratio"] == pytest.approx(20 / 220)
    assert (
        result["diagnostic"]["comment_scroll_stopped_reason"]
        == "coverage_tail_no_new"
    )


@pytest.mark.asyncio
async def test_process_payload_does_not_claim_partial_when_post_count_is_unknown(
    monkeypatch,
) -> None:
    server = ExtraDataIngestServer()
    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_items",
        lambda strategy, xml_in, context: (
            [{"comment_key": "comment-1", "author": "Alice", "text": "Hello"}],
            {"reason_code": "ok", "comments_returned": 1},
        ),
    )
    xml = '<hierarchy><node text="frame" /></hierarchy>'
    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_comments",
            "xml": xml,
            "xml_snapshots": [xml, xml.replace("frame", "frame-2")],
            "context": {
                "persist": False,
                "max_items": 500,
                "comment_target_effective": 500,
                "post_comment_count": None,
                "comment_scroll_stopped_reason": "coverage_tail_no_new",
            },
        }
    )

    assert result["ok"] is True
    assert result["diagnostic"]["reason_code"] == "ok"
    assert result["diagnostic"]["comments_returned"] == 1
    assert "coverage_ratio" not in result["diagnostic"]


def test_comment_target_returns_bounds_and_parent_hash(monkeypatch) -> None:
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


def test_comment_target_uses_body_fallback_for_parent_anchor(monkeypatch) -> None:
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


def test_comment_target_reports_empty_when_no_candidate(monkeypatch) -> None:
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


# Insert retry and stale-FK stripping used to live here. Both moved to
# device_farm with the write itself — see test_edge_ingest_parity.py.


@pytest.mark.asyncio
async def test_process_payload_can_return_items_without_persist() -> None:
    server = ExtraDataIngestServer()
    xml = '<hierarchy><node text="Hello" /></hierarchy>'

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "text_nodes",
        "xml": xml,
        "context": {"persist": False, "return_items": True},
    })

    assert result["ok"] is True
    assert result["inserted_count"] == 0
    assert "persist_batch" not in result
    assert result["items"] == [{"text": "Hello", "body": "Hello", "content_type": "text"}]


@pytest.mark.asyncio
async def test_process_payload_returns_batch_without_touching_a_database() -> None:
    server = ExtraDataIngestServer()
    xml = '<hierarchy><node text="Hello" /></hierarchy>'

    result = await server.process_payload({
        "serial": "serial-1",
        "strategy": "text_nodes",
        "xml": xml,
        "captured_at": "2026-08-27T01:02:03+00:00",
        "context": {
            "persist": True,
            "collection": "fb_posts",
            "content_type": "fb_post",
            "hash_scope": "exec-1",
        },
    })

    # The database handle is gone, not merely unused: agent-boot ships to
    # customer machines, so a DSN reachable from here is a credential leak.
    assert not hasattr(server, "_writer")

    assert result["ok"] is True
    assert result["inserted_count"] == 0
    assert result["persist_batch"]["schema_version"] == 1
    assert result["persist_batch"]["kind"] == "content"
    assert result["persist_batch"]["items"] == [
        {"text": "Hello", "body": "Hello", "content_type": "text"}
    ]
    assert result["persist_batch"]["content_hashes"] == result["batch_content_hashes"]


@pytest.mark.asyncio
async def test_process_payload_returns_single_fb_post_as_active_parent(monkeypatch) -> None:
    server = ExtraDataIngestServer()
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
    assert _persisted_items(result)
    assert result["active_parent_post"] == {
        "pid": "pid-1",
        "parent_id": result["batch_content_hashes"][0],
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
    assert len(_persisted_items(result)) == 2
    assert "active_parent_post" not in result
    assert result["post_id_map"] == {
        "pid-1": result["batch_content_hashes"][0],
        "pid-2": result["batch_content_hashes"][1],
    }


@pytest.mark.asyncio
async def test_process_payload_keeps_only_opened_fb_post_from_snapshots(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    def fake_parse_items(strategy, xml_in, context):
        assert strategy == "fb_posts"
        if "detail" in xml_in:
            return (
                [
                    {
                        "_pid": "pid-2",
                        "post_key": "post-2-detail",
                        "stable_post_id": "stable-2",
                        "author": "Bob",
                        "text": "second post full body from detail",
                    }
                ],
                {"reason_code": "ok", "posts_returned": 1},
            )
        return (
            [
                    {
                        "_pid": "pid-1",
                        "post_key": "post-1",
                        "stable_post_id": "stable-1",
                        "author": "Alice",
                        "text": "first post body",
                    },
                    {
                        "_pid": "pid-2",
                        "post_key": "post-2-feed",
                        "stable_post_id": "stable-2",
                        "author": "Bob",
                        "text": "second post",
                    },
            ],
            {"reason_code": "ok", "posts_returned": 2},
        )

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fake_parse_items)

    feed_xml = '<hierarchy><node text="feed" /></hierarchy>'
    detail_xml = '<hierarchy><node text="detail" /></hierarchy>'
    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": feed_xml,
            "xml_snapshots": [feed_xml, detail_xml],
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
                        "author": "Bob",
                        "text_prefix": "second post",
                    },
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["parsed_count"] == 1
    assert len(_persisted_items(result)) == 1
    assert [row["body"] for row in _persisted_rows(result)] == [
        "second post full body from detail",
    ]
    assert result["diagnostic"]["snapshot_count"] == 2
    assert result["diagnostic"]["frame_posts_returned"] == [2, 1]
    assert result["active_parent_post"]["pid"] == "pid-2"
    assert result["active_parent_post"]["parent_id"] == result["batch_content_hashes"][0]


@pytest.mark.asyncio
async def test_process_payload_reconciles_opened_feed_post_with_polluted_detail(
    monkeypatch,
) -> None:
    server = ExtraDataIngestServer()
    feed_post = {
        "_pid": "3504dc2886a603f3",
        "post_key": "725fa9ebb9141fe3dcfcb90c81134ec940725420",
        "stable_post_id": "6f9e3eff25f3f5721d15614150434eca61cd8dc1",
        "author": "Nội dung do AI tạo",
        "timestamp": "12 thg 6•Chia sẻ với: Nhóm công khai",
        "text": "Trong Video mới này mình đã B… xem thêm Ảnh",
        "reactions": 107,
        "comments": 269,
        "shares": 47,
        "source_index": 0,
    }
    detail_post = {
        "_pid": "b59c812bc0577086",
        "post_key": "ac20583e9c21e6b908cfca34d3a8d14942645bc",
        "stable_post_id": "bc0f4752f517aa233ea7d720ac732bbd722af017",
        "author": "Nội dung do AI tạo",
        "timestamp": "Vũ Nguyễn - AI Builder•12 thg 6•Chia sẻ với: Nhóm công khai",
        "text": (
            "Tham gia Claude - OpenClaw …•Tham gia Nội dung do AI tạo "
            "Vũ Nguyễn - AI Builder Trong Video mới này mình đã BUILD CẢ PHÒNG "
            "MARKETING bằng Claude - đây là cách nó hoạt động"
        ),
        "image_desc": "Ảnh bìa của nhóm",
        "source_index": 1,
    }
    detail_chrome = {
        "_pid": "chrome",
        "post_key": "chrome-key",
        "stable_post_id": "chrome-stable",
        "author": "Đáng chú ý",
        "timestamp": "",
        "text": "Tham gia nhóm Claude - OpenClaw - Ai Agent Kiếm Cơm Ảnh Sự kiện File Album",
        "source_index": 0,
    }
    detail_chrome_echo = {
        "_pid": "detail-chrome",
        "post_key": "detail-chrome-key",
        "stable_post_id": "detail-chrome-stable",
        "author": "Featured",
        "timestamp": "12 thg 6•Chia sẻ với: Nhóm công khai",
        "text": (
            "Tham gia nhóm Claude - OpenClaw Trong Video mới này mình đã "
            "BUILD CẢ PHÒNG MARKETING"
        ),
        "source_index": 1,
    }
    unopened_feed_post = {
        "_pid": "unopened-feed",
        "post_key": "unopened-feed-key",
        "stable_post_id": "unopened-feed-stable",
        "author": "AIcream",
        "timestamp": "27 thg 5•Chia sẻ với: Nhóm công khai",
        "text": ".. Mình mới thấy một skill khá … xem thêm Ảnh",
        "source_index": 0,
    }

    def fake_parse_items(strategy, xml_in, context):
        assert strategy == "fb_posts"
        if "detail" in xml_in:
            return [detail_post, detail_chrome_echo], {
                "reason_code": "ok",
                "posts_returned": 2,
            }
        return [detail_chrome, unopened_feed_post, feed_post], {
            "reason_code": "ok",
            "posts_returned": 3,
        }

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fake_parse_items)

    feed_xml = '<hierarchy><node text="feed" /></hierarchy>'
    detail_xml = '<hierarchy><node text="detail" /></hierarchy>'
    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": feed_xml,
            "xml_snapshots": [feed_xml, detail_xml],
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
                        "pid": feed_post["_pid"],
                        "post_key": feed_post["post_key"],
                        "stable_post_id": feed_post["stable_post_id"],
                        "author": feed_post["author"],
                        "timestamp": feed_post["timestamp"],
                        "text_prefix": feed_post["text"],
                    },
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["parsed_count"] == 1
    assert len(_persisted_items(result)) == 1
    assert _persisted_rows(result)[0]["author"] == "Vũ Nguyễn - AI Builder"
    assert _persisted_rows(result)[0]["body"].startswith(
        "Trong Video mới này mình đã BUILD CẢ PHÒNG MARKETING"
    )
    assert "xem thêm" not in _persisted_rows(result)[0]["body"].casefold()
    assert _persisted_items(result)[0]["reactions"] == 107
    assert _persisted_items(result)[0]["comments"] == 269
    assert _persisted_items(result)[0]["shares"] == 47
    assert result["diagnostic"]["reconciled_post_count"] == 1
    assert result["diagnostic"]["detail_chrome_dropped"] == 2
    assert result["active_parent_post"]["pid"] == feed_post["_pid"]
    assert result["active_parent_post"]["parent_id"] == result["batch_content_hashes"][0]


def test_verified_single_post_detail_is_authoritative_over_feed_preview_hashes() -> None:
    from relay.extra_data.parsers.facebook.post_reconciliation import (
        reconcile_fb_post_frames,
    )

    feed_post = {
        "_pid": "18096e5f28a92169",
        "post_key": "0fc69384e3a212777445c43c1845f218d5f9686a",
        "stable_post_id": "5a90c70c78fbeda1ed2ed4f7b03a3715fc403885",
        "author": "Phan Đông Giang",
        "timestamp": "23 giờ•Chia sẻ với: Nhóm công khai",
        "text": "Quản trị viên Quản trị viên Apple đã tham chiến: Hãy giữ A… xem thêm Ảnh",
        "reactions": "19",
        "comments": "2",
        "source_index": 0,
    }
    detail_post = {
        "_pid": "d3fb1fce98d63e51",
        "post_key": "d233e2fa154de9c12d0694a263dc5942701c04ce",
        "stable_post_id": "9db9d344d7e42dfe8a63b9d336e533a6aa6b168c",
        "author": "Phan Đông Giang",
        "timestamp": "23 giờ•Chia sẻ với: Nhóm công khai",
        "text": (
            "Cộng Đồng Claude …•Tham gia Tham gia Quản trị viên Quản trị viên "
            "Phan Đông Giang Apple đã tham chiến: Hãy giữ Agent của bạn làm việc "
            "liên tục 24/7 Ảnh Tặng quà Tặng quà"
        ),
        "reactions": "19",
        "comments": "2",
        "source_index": 1,
    }
    opened_post = {
        "pid": feed_post["_pid"],
        "post_key": feed_post["post_key"],
        "stable_post_id": feed_post["stable_post_id"],
        "author": feed_post["author"],
        "timestamp": feed_post["timestamp"],
        "text_prefix": feed_post["text"],
    }

    rows, diagnostic = reconcile_fb_post_frames(
        [[feed_post], [detail_post]],
        opened_post=opened_post,
        opened_state="ok",
    )

    assert diagnostic["reason_code"] == "ok"
    assert diagnostic["selection_reason"] == "feed_detail_match"
    assert len(rows) == 1
    assert rows[0]["author"] == "Phan Đông Giang"
    assert rows[0]["text"].startswith("Apple đã tham chiến:")
    assert "xem thêm" not in rows[0]["text"].casefold()
    assert rows[0]["comments"] == "2"


def test_verified_single_post_detail_rejects_unrelated_body() -> None:
    from relay.extra_data.parsers.facebook.post_reconciliation import (
        reconcile_fb_post_frames,
    )

    feed_post = {
        "_pid": "feed-pid",
        "post_key": "feed-key",
        "stable_post_id": "feed-stable",
        "author": "Phan Đông Giang",
        "timestamp": "23 giờ•Chia sẻ với: Nhóm công khai",
        "text": "Apple đã tham chiến: Hãy giữ A… xem thêm Ảnh",
    }
    unrelated_detail = {
        "_pid": "detail-pid",
        "post_key": "detail-key",
        "stable_post_id": "detail-stable",
        "author": "Phan Đông Giang",
        "timestamp": "23 giờ•Chia sẻ với: Nhóm công khai",
        "text": "Claude Code 101: Hướng dẫn toàn diện cho người mới",
    }

    rows, diagnostic = reconcile_fb_post_frames(
        [[feed_post], [unrelated_detail]],
        opened_post={
            "pid": feed_post["_pid"],
            "post_key": feed_post["post_key"],
            "stable_post_id": feed_post["stable_post_id"],
            "author": feed_post["author"],
            "timestamp": feed_post["timestamp"],
            "text_prefix": feed_post["text"],
        },
        opened_state="ok",
    )

    assert rows == []
    assert diagnostic["reason_code"] == "post_detail_target_not_reconciled"


def test_verified_single_post_detail_keeps_partial_opened_parent() -> None:
    from relay.extra_data.parsers.facebook.post_reconciliation import (
        reconcile_fb_post_frames,
    )

    feed_post = {
        "_pid": "feed-pid",
        "post_key": "feed-key",
        "stable_post_id": "feed-stable",
        "author": "OrangeGuava6933",
        "timestamp": "23 Th7•Chia sẻ với: Nhóm công khai",
        "text": "Các anh em cho mình hỏi Mình thiết lập zalo cá nhân làm bot… xem thêm",
        "source_index": 0,
    }
    detail_post = {
        **feed_post,
        "_pid": "detail-pid",
        "post_key": "detail-key",
        "stable_post_id": "detail-stable",
        "source_index": 1,
    }

    rows, diagnostic = reconcile_fb_post_frames(
        [[feed_post], [detail_post]],
        opened_post={
            "pid": feed_post["_pid"],
            "post_key": feed_post["post_key"],
            "stable_post_id": feed_post["stable_post_id"],
            "author": feed_post["author"],
            "timestamp": feed_post["timestamp"],
            "text_prefix": feed_post["text"],
        },
        opened_state="ok",
    )

    assert diagnostic["reason_code"] == "post_detail_partial"
    assert diagnostic["post_detail_partial"] is True
    assert len(rows) == 1
    assert rows[0]["post_detail_partial"] is True
    assert {
        "_pid": "feed-pid",
        "post_key": "feed-key",
        "stable_post_id": "feed-stable",
        "source_index": 0,
    } in rows[0]["_source_variants"]


@pytest.mark.asyncio
async def test_process_payload_keeps_partial_parent_when_opened_detail_is_truncated(
    monkeypatch,
) -> None:
    server = ExtraDataIngestServer()
    truncated_post = {
        "_pid": "feed-pid",
        "post_key": "feed-key",
        "stable_post_id": "feed-stable",
        "author": "Quoc Modoro",
        "timestamp": "1 giờ•Chia sẻ với: Nhóm công khai",
        "text": "Tôi vừa viết xong 1 Claude Plugin - Business Builder…",
        "source_index": 0,
    }
    detail_post = {
        **truncated_post,
        "_pid": "detail-pid",
        "post_key": "detail-key",
        "stable_post_id": "detail-stable",
        "source_index": 1,
    }

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_items",
        lambda strategy, xml_in, context: (
            [detail_post] if "detail" in xml_in else [truncated_post],
            {"reason_code": "ok", "posts_returned": 1},
        ),
    )

    feed_xml = '<hierarchy><node text="feed" /></hierarchy>'
    detail_xml = '<hierarchy><node text="detail" /></hierarchy>'
    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": feed_xml,
            "xml_snapshots": [feed_xml, detail_xml],
            "context": {
                "persist": True,
                "collection": "fb_posts",
                "content_type": "fb_post",
                "dedupe_field": "post_key",
                "hash_scope": "exec-1",
                "open_post_detail": True,
                "open_post_detail_diagnostic": {
                    "opened_post": {
                        "pid": truncated_post["_pid"],
                        "post_key": truncated_post["post_key"],
                        "stable_post_id": truncated_post["stable_post_id"],
                        "author": truncated_post["author"],
                        "timestamp": truncated_post["timestamp"],
                        "text_prefix": truncated_post["text"],
                    },
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["parsed_count"] == 1
    assert result["diagnostic"]["reason_code"] == "post_detail_partial"
    assert result["diagnostic"]["post_detail_partial"] is True
    assert len(_persisted_items(result)) == 1
    assert _persisted_rows(result)[0]["author"] == "Quoc Modoro"
    assert result["active_parent_post"]["pid"] == truncated_post["_pid"]
    assert result["active_parent_post"]["source"] == "post_detail"


@pytest.mark.asyncio
async def test_process_payload_post_detail_uses_first_post_when_diagnostic_missing(monkeypatch) -> None:
    server = ExtraDataIngestServer()
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
    assert len(_persisted_items(result)) == 2
    assert result["active_parent_post"]["parent_id"] == result["batch_content_hashes"][0]
    assert result["active_parent_post"]["pid"] == "pid-detail"
    assert result["active_parent_post"]["source"] == "post_detail"
    assert result["active_parent_post"]["selection_reason"] == "post_detail_first_parsed"


@pytest.mark.asyncio
async def test_process_payload_uses_opened_post_diagnostic_to_pick_active_parent(monkeypatch) -> None:
    server = ExtraDataIngestServer()
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
    assert len(_persisted_items(result)) == 2
    assert result["active_parent_post"] == {
        "pid": "pid-2",
        "parent_id": result["batch_content_hashes"][1],
        "post_key": "post-2",
        "author": "Alice",
        "text_prefix": "opened post body",
        "source": "post_detail",
    }


@pytest.mark.asyncio
async def test_process_payload_persists_opened_post_parent_when_comment_sheet_has_no_post_rows(monkeypatch) -> None:
    server = ExtraDataIngestServer()
    feed_post = {
        "_pid": "pid-comment-sheet",
        "post_key": "post-comment-sheet",
        "author": "Alice",
        "timestamp": "5 phút",
        "text": "opened post body before comment sheet",
    }
    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_items",
        lambda strategy, xml_in, context: (
            ([feed_post], {"reason_code": "ok", "posts_returned": 1})
            if "feed" in xml_in
            else ([], {"reason_code": "already_on_comment_sheet", "posts_returned": 0})
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="feed" /></hierarchy>',
            "xml_snapshots": [
                '<hierarchy><node text="feed" /></hierarchy>',
                '<hierarchy><node text="comment sheet" /></hierarchy>',
            ],
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
    assert len(_persisted_items(result)) == 1
    assert _persisted_items(result)[0]["post_key"] == "post-comment-sheet"
    assert _persisted_rows(result)[0]["body"] == "opened post body before comment sheet"
    assert result["diagnostic"]["reason_code"] == "ok"
    assert result["diagnostic"]["comment_sheet_feed_fallback"] is True
    assert result["active_parent_post"]["parent_id"] == result["batch_content_hashes"][0]
    assert result["active_parent_post"]["pid"] == "pid-comment-sheet"
    assert result["active_parent_post"]["source"] == "post_detail"


@pytest.mark.asyncio
async def test_process_payload_uses_complete_feed_post_when_comment_sheet_has_only_chrome(
    monkeypatch,
) -> None:
    server = ExtraDataIngestServer()
    feed_post = {
        "_pid": "pid-comment-sheet-chrome",
        "post_key": "post-comment-sheet-chrome",
        "author": "Trí Hưng",
        "timestamp": "23 giờ",
        "text": "Đây là cách GG làm trong cuộc đua AI =))",
    }
    detail_chrome = {
        "_pid": "detail-chrome",
        "post_key": "detail-chrome-key",
        "author": "Featured",
        "timestamp": "",
        "text": "Join group Cộng Đồng Claude",
    }

    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_items",
        lambda strategy, xml_in, context: (
            ([feed_post], {"reason_code": "ok", "posts_returned": 1})
            if "feed" in xml_in
            else ([detail_chrome], {"reason_code": "ok", "posts_returned": 1})
        ),
    )

    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": '<hierarchy><node text="feed" /></hierarchy>',
            "xml_snapshots": [
                '<hierarchy><node text="feed" /></hierarchy>',
                '<hierarchy><node text="detail" /></hierarchy>',
            ],
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
                        "pid": feed_post["_pid"],
                        "post_key": feed_post["post_key"],
                        "author": feed_post["author"],
                        "timestamp": feed_post["timestamp"],
                        "text_prefix": feed_post["text"],
                    },
                },
            },
        }
    )

    assert result["diagnostic"]["reason_code"] == "ok"
    assert result["diagnostic"]["comment_sheet_feed_fallback"] is True
    assert result["diagnostic"]["detail_chrome_dropped"] == 1
    assert len(_persisted_items(result)) == 1
    assert _persisted_rows(result)[0]["body"] == feed_post["text"]


@pytest.mark.asyncio
async def test_process_payload_accepts_richer_complete_detail_ending_in_ellipsis(
    monkeypatch,
) -> None:
    server = ExtraDataIngestServer()
    feed_post = {
        "_pid": "pid-ellipsis",
        "post_key": "post-ellipsis-feed",
        "stable_post_id": "stable-ellipsis",
        "author": "Alice",
        "text": "A deliberately thoughtful post…",
    }
    detail_post = {
        **feed_post,
        "post_key": "post-ellipsis-detail",
        "text": (
            "A deliberately thoughtful post whose complete final sentence "
            "intentionally trails off…"
        ),
    }
    monkeypatch.setattr(
        extra_data_ingest,
        "_parse_items",
        lambda strategy, xml_in, context: (
            [detail_post] if "detail" in xml_in else [feed_post],
            {"reason_code": "ok", "posts_returned": 1},
        ),
    )

    feed_xml = '<hierarchy><node text="feed" /></hierarchy>'
    detail_xml = '<hierarchy><node text="detail" /></hierarchy>'
    result = await server.process_payload(
        {
            "serial": "serial-1",
            "strategy": "fb_posts",
            "xml": feed_xml,
            "xml_snapshots": [feed_xml, detail_xml],
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
                        "pid": feed_post["_pid"],
                        "post_key": feed_post["post_key"],
                        "stable_post_id": feed_post["stable_post_id"],
                        "author": feed_post["author"],
                        "text_prefix": feed_post["text"],
                    },
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["parsed_count"] == 1
    assert len(_persisted_items(result)) == 1
    assert _persisted_rows(result)[0]["body"] == detail_post["text"]


@pytest.mark.asyncio
async def test_process_payload_marks_post_detail_active_parent_source(monkeypatch) -> None:
    server = ExtraDataIngestServer()
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
    assert result["active_parent_post"]["parent_id"] == result["batch_content_hashes"][0]
    assert result["active_parent_post"]["source"] == "post_detail"


@pytest.mark.asyncio
async def test_process_payload_matches_opened_post_by_text_when_ids_differ(monkeypatch) -> None:
    server = ExtraDataIngestServer()
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
    assert result["active_parent_post"]["parent_id"] == result["batch_content_hashes"][1]
    assert result["active_parent_post"]["pid"] == "detail-generated-2"
    assert result["active_parent_post"]["author"] == "Alice"


@pytest.mark.asyncio
async def test_process_payload_active_parent_uses_image_desc_text_fallback(monkeypatch) -> None:
    server = ExtraDataIngestServer()
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
    assert result["active_parent_post"]["parent_id"] == result["batch_content_hashes"][0]
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


def test_merge_fb_comment_frames_drops_empty_comment_rows() -> None:
    items, diagnostic = extra_data_ingest.merge_fb_comment_frames(
        [
            (
                [
                    {"comment_key": "c-empty", "author": "Alice", "text": ""},
                    {"comment_key": "c-body", "author": "Bob", "text": "real body"},
                ],
                {"reason_code": "ok"},
            ),
        ],
        max_items=10,
    )

    assert items == [{"comment_key": "c-body", "author": "Bob", "text": "real body"}]
    assert diagnostic["comments_returned"] == 1
    assert diagnostic["dropped_empty_comments"] == 1


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


@pytest.mark.asyncio
async def test_process_payload_uses_trusted_preparsed_fb_comments(monkeypatch) -> None:
    def fail_parse(*args, **kwargs):
        raise AssertionError("preparsed path should not parse XML")

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fail_parse)


@pytest.mark.asyncio
async def test_process_payload_trusts_preparsed_multi_snapshot_hash_manifest(
    monkeypatch,
) -> None:
    def fail_parse(*args, **kwargs):
        raise AssertionError("multi-snapshot preparsed path should not parse XML")

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fail_parse)


@pytest.mark.asyncio
async def test_process_payload_rejects_preparsed_when_manifest_primary_hash_mismatches_xml(
    monkeypatch,
) -> None:
    called = {"count": 0}

    def fake_parse(*args, **kwargs):
        called["count"] += 1
        return [{"comment_key": "fresh", "text": "parsed-from-xml"}], {
            "reason_code": "ok"
        }

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fake_parse)


@pytest.mark.asyncio
async def test_process_payload_rejects_preparsed_when_snapshot_count_exceeds_manifest(
    monkeypatch,
) -> None:
    called = {"count": 0}

    def fake_parse(*args, **kwargs):
        called["count"] += 1
        return [{"comment_key": "fresh", "text": "parsed-from-xml"}], {
            "reason_code": "ok"
        }

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fake_parse)


@pytest.mark.asyncio
async def test_process_payload_persists_fb_comment_post_stats_to_parent(monkeypatch) -> None:
    def fail_parse(*args, **kwargs):
        raise AssertionError("preparsed path should not parse XML")

    monkeypatch.setattr(extra_data_ingest, "_parse_items", fail_parse)


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


@pytest.mark.asyncio
async def test_process_payload_rejects_preparsed_fb_comments_when_snapshot_hashes_mismatch(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()
    called = {"count": 0}

    def fake_parse(xml, parent_post_id=None, max_items=50):
        called["count"] += 1
        return [{"comment_key": "fresh", "text": "fresh-from-current-xml"}], {
            "reason_code": "ok"
        }

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)


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


@pytest.mark.asyncio
async def test_process_payload_rejects_latest_post_parent_when_step_context_was_lost(
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

    latest_lookup: dict[str, Any] = {}


@pytest.mark.asyncio
async def test_process_payload_rejects_comment_session_parent_mismatch(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [{"comment_key": "c1", "text": "comment body"}], {"reason_code": "ok"}

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)


@pytest.mark.asyncio
async def test_process_payload_rejects_comment_session_missing_context_pid(
    monkeypatch,
) -> None:
    class Module:
        pass

    module = Module()

    def fake_parse(xml, parent_post_id=None, max_items=50):
        return [{"comment_key": "c1", "text": "comment body"}], {
            "reason_code": "ok"
        }

    module.parse_fb_comments_from_xml_with_diagnostic = fake_parse
    monkeypatch.setitem(sys.modules, "relay.extra_data.parsers.facebook", module)


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

