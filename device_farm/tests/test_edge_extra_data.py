from __future__ import annotations

import threading

import pytest
from types import SimpleNamespace

from tasks.scenario.steps import control_flow
from tasks.scenario.steps import extraction as extraction_mod


class _FakeDevice:
    serial = "serial-1"

    def __init__(self, response):
        self.response = response
        self.calls = []

    def request_extra_data_xml(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _SwipeTrackingFakeDevice(_FakeDevice):
    def __init__(self, response):
        super().__init__(response)
        self.swipes = []

    def swipe(self, *args, **kwargs):
        self.swipes.append((args, kwargs))


class _SequenceFakeDevice(_FakeDevice):
    def __init__(self, responses):
        super().__init__(responses[0] if responses else {"ok": True})
        self.responses = list(responses)

    def request_extra_data_xml(self, **kwargs):
        self.calls.append(kwargs)
        if self.responses:
            return self.responses.pop(0)
        return self.response


def _ctx(device):
    return SimpleNamespace(
        serial="serial-1",
        device=device,
        ctx={},
        scenario={
            "_execution_id": "exec",
            "_campaign_id": "camp",
            "_campaign_vars": {"__USER_ID__": "user"},
            "_run_hash_scope": "scope",
            "name": "scenario",
        },
        cancel_event=None,
    )


@pytest.fixture(autouse=True)
def _relay_available(monkeypatch):
    monkeypatch.setattr(extraction_mod, "_relay_extra_data_available", lambda _device: True)


def test_resolve_org_id_for_edge_from_user_id(monkeypatch) -> None:
    monkeypatch.setattr("db.database.run_activity_coro", lambda _coro: "org-from-user")

    org_id = extraction_mod._resolve_org_id_for_edge(
        "serial-1",
        {"_campaign_vars": {"__USER_ID__": "user-abc"}},
    )
    assert org_id == "org-from-user"


def test_try_edge_extra_data_success(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 1,
            "duplicate_count": 1,
            "diagnostic": {"reason_code": "ok"},
            "items": [{"post_key": "p1", "text": "hello"}],
        },
        "route": "relay_u2",
    })
    sc = _ctx(device)
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "dedupe_field": "post_key", "edge_extra_data": True},
        "fb_posts",
        result,
    )

    assert handled is True
    assert result["extracted"] == 1
    assert result["duplicate_count"] == 1
    assert device.calls[0]["strategy"] == "fb_posts"
    assert device.calls[0]["context"]["user_id"] == "user"
    assert "endpoint" not in device.calls[0]
    assert device.calls[0]["context"]["persist"] is True
    assert device.calls[0]["context"]["return_items"] is False
    assert device.calls[0]["cancel_event"] is None
    assert result["edge_extra_summary"]["items_omitted"] == 1
    assert "posts" not in sc.ctx


def test_try_edge_extra_data_propagates_cancel_event(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    event = threading.Event()
    device = _FakeDevice({
        "ok": False,
        "error": "cancelled",
        "cancelled": True,
    })
    sc = _ctx(device)
    sc.cancel_event = event
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "dedupe_field": "post_key", "edge_extra_data": True},
        "fb_posts",
        result,
    )

    assert handled is True
    assert result["cancelled"] is True
    assert device.calls[0]["cancel_event"] is event


def test_try_edge_extra_data_no_relay(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setattr(extraction_mod, "_relay_extra_data_available", lambda _d: False)
    device = _FakeDevice({"ok": True})
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {"collection": "fb", "edge_extra_data": True},
        "fb_posts",
        result,
    )

    assert handled is True
    assert result["ok"] is False
    assert "no relay" in result["message"]
    assert device.calls == []


def test_try_edge_extra_data_can_return_items_when_requested(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "items": [{"post_key": "p1", "text": "hello"}],
        },
    })
    sc = _ctx(device)
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "dedupe_field": "post_key",
            "edge_extra_data": True,
            "return_items": True,
        },
        "fb_posts",
        result,
    )

    assert handled is True
    assert device.calls[0]["context"]["return_items"] is True
    assert sc.ctx["posts"] == [{"post_key": "p1", "text": "hello"}]


def test_fb_posts_batch_sets_active_parent_for_later_comments(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "post_id_map": {"pid-1": "scoped-parent-hash"},
            "active_parent_post": {
                "pid": "pid-1",
                "parent_id": "scoped-parent-hash",
                "post_key": "post-1",
                "stable_post_id": "stable-1",
                "fb_post_id": "fb-1",
                "author": "Alice",
                "timestamp": "1 giờ",
                "text_prefix": "parent post body",
            },
        },
    })
    sc = _ctx(device)

    handled_posts = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True, "dedupe_field": "post_key"},
        "fb_posts",
        {},
    )

    assert handled_posts is True
    assert sc.ctx["_active_comment_parent_hash"] == "scoped-parent-hash"
    assert sc.ctx["_fb_comment_parent_pid"] == "pid-1"
    assert sc.ctx["_active_comment_parent_anchor"] == {
        "pid": "pid-1",
        "post_key": "post-1",
        "stable_post_id": "stable-1",
        "fb_post_id": "fb-1",
        "author": "Alice",
        "timestamp": "1 giờ",
        "text_prefix": "parent post body",
    }

    device.response = {
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    }
    handled_comments = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True},
        "fb_comments",
        {},
    )

    assert handled_comments is True
    comment_context = device.calls[-1]["context"]
    assert comment_context["parent_id"] == "scoped-parent-hash"
    assert comment_context["parent_id_already_scoped"] is True
    assert comment_context["parent_post_id"] == "pid-1"
    assert comment_context["_active_comment_parent_anchor"]["text_prefix"] == "parent post body"


def test_fb_post_detail_parent_source_is_forwarded_to_comment_extract(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "active_parent_post": {
                "pid": "pid-detail",
                "parent_id": "detail-parent-hash",
                "post_key": "post-detail",
                "text_prefix": "opened detail post",
                "source": "post_detail",
            },
        },
    })
    sc = _ctx(device)

    handled_posts = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True, "dedupe_field": "post_key"},
        "fb_posts",
        {},
    )

    assert handled_posts is True
    assert sc.ctx["_active_comment_parent_source"] == "post_detail"

    device.response = {
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    }
    handled_comments = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True},
        "fb_comments",
        {},
    )

    assert handled_comments is True
    comment_context = device.calls[-1]["context"]
    assert comment_context["parent_id"] == "detail-parent-hash"
    assert comment_context["parent_post_id"] == "pid-detail"
    assert comment_context["parent_context_source"] == "post_detail"


def test_fb_posts_multi_post_map_does_not_guess_active_comment_parent(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 2,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "post_id_map": {
                "pid-1": "scoped-parent-1",
                "pid-2": "scoped-parent-2",
            },
        },
    })
    sc = _ctx(device)
    sc.ctx["_active_comment_parent_hash"] = "stale-parent"
    sc.ctx["_fb_comment_parent_pid"] = "stale-pid"
    sc.ctx["_active_comment_parent_anchor"] = {"pid": "stale-pid"}
    sc.ctx["_active_comment_anchor_verified"] = True

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True, "dedupe_field": "post_key"},
        "fb_posts",
        {},
    )

    assert handled is True
    assert sc.ctx["_post_id_map"] == {
        "pid-1": "scoped-parent-1",
        "pid-2": "scoped-parent-2",
    }
    assert "_active_comment_parent_hash" not in sc.ctx
    assert "_fb_comment_parent_pid" not in sc.ctx
    assert "_active_comment_parent_anchor" not in sc.ctx
    assert "_active_comment_anchor_verified" not in sc.ctx


def test_fb_posts_active_parent_metadata_wins_over_multi_post_map(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 2,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "post_id_map": {
                "pid-1": "scoped-parent-1",
                "pid-2": "scoped-parent-2",
            },
            "active_parent_post": {
                "pid": "pid-2",
                "parent_id": "scoped-parent-2",
                "author": "Bob",
                "text_prefix": "opened post body",
            },
        },
    })
    sc = _ctx(device)

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True, "dedupe_field": "post_key"},
        "fb_posts",
        {},
    )

    assert handled is True
    assert sc.ctx["_active_comment_parent_hash"] == "scoped-parent-2"
    assert sc.ctx["_fb_comment_parent_pid"] == "pid-2"
    assert sc.ctx["_active_comment_parent_anchor"] == {
        "pid": "pid-2",
        "author": "Bob",
        "text_prefix": "opened post body",
    }


def test_fb_posts_pid_map_single_entry_forwards_post_detail_source(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "post_id_map": {"pid-opened": "scoped-parent-opened"},
        },
    })
    sc = _ctx(device)

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb_group_posts", "edge_extra_data": True, "dedupe_field": "post_key"},
        "fb_posts",
        {},
    )

    assert handled is True
    assert sc.ctx["_active_comment_parent_hash"] == "scoped-parent-opened"
    assert sc.ctx["_fb_comment_parent_pid"] == "pid-opened"
    assert sc.ctx["_active_comment_parent_source"] == "post_detail"
    assert sc.ctx["_active_comment_anchor_verified"] is True

    device.response = {
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 2,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    }
    extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb_group_posts",
            "edge_extra_data": True,
            "require_verified_parent": True,
        },
        "fb_comments",
        {},
    )
    comment_context = device.calls[-1]["context"]
    assert comment_context["parent_context_source"] == "post_detail"
    assert comment_context["parent_id"] == "scoped-parent-opened"
    assert comment_context["parent_post_id"] == "pid-opened"


def test_fb_comments_without_active_parent_does_not_forward_stale_parent_context(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    })

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {"collection": "fb", "edge_extra_data": True},
        "fb_comments",
        {},
    )

    assert handled is True
    request = device.calls[-1]
    assert request["strategy"] == "fb_comments"
    context = request["context"]
    assert context["parent_id"] is None
    assert context["parent_id_already_scoped"] is False
    assert context["parent_post_id"] is None
    assert context["_active_comment_parent_anchor"] is None


def test_comment_target_request_forwards_locked_post_anchor(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "target": {"bounds": [1, 2, 3, 4], "pid": "pid-1"},
            },
        },
    })
    sc = _ctx(device)
    sc.ctx["_active_comment_parent_source"] = "post_detail"
    sc.ctx["_active_comment_parent_hash"] = "scoped-parent"
    sc.ctx["_fb_comment_parent_pid"] = "pid-1"
    sc.ctx["_active_comment_parent_anchor"] = {
        "pid": "pid-1",
        "post_key": "post-1",
        "author": "Alice",
        "text_prefix": "opened post",
    }
    result = {}

    target = extraction_mod.request_edge_comment_target(
        device=sc.device,
        serial=sc.serial,
        ctx=sc.ctx,
        scenario=sc.scenario,
        step={},
        result=result,
    )

    assert target is not None
    context = device.calls[-1]["context"]
    assert context["_active_comment_parent_anchor"]["post_key"] == "post-1"
    assert context["parent_context_source"] == "post_detail"
    assert context["parent_id"] == "scoped-parent"
    assert context["parent_post_id"] == "pid-1"


def test_try_edge_extra_data_reports_failure_without_server_fallback(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({"ok": False, "error": "no_relay"})
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {"collection": "fb", "edge_extra_data": True},
        "fb_posts",
        result,
    )

    assert handled is True
    assert result["ok"] is False
    assert "no_relay" in result["message"]


def test_try_edge_extra_data_defaults_content_strategy_to_agent_boot(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}})
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {"collection": "fb"},
        "fb_posts",
        result,
    )

    assert handled is True
    assert device.calls[0]["strategy"] == "fb_posts"


def test_text_nodes_routes_to_agent_boot_without_collection(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 0,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "items": [{"text": "hello"}, {"body": "world"}],
        },
    })
    sc = _ctx(device)
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"edge_extra_data": True},
        "text_nodes",
        result,
    )

    assert handled is True
    assert device.calls[0]["strategy"] == "text_nodes"
    assert device.calls[0]["context"]["persist"] is False
    assert device.calls[0]["context"]["return_items"] is True
    assert sc.ctx["text_nodes"] == ["hello", "world"]
    assert result["extracted"] == 2


def test_text_nodes_null_edge_extra_flag_still_routes_to_agent_boot(monkeypatch) -> None:
    """UI used to set edge_extra_data: undefined (JSON null) when switching strategy."""
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 0,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "items": [{"text": "line"}],
        },
    })
    sc = _ctx(device)
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"strategy": "text_nodes", "edge_extra_data": None},
        "text_nodes",
        result,
    )

    assert handled is True
    assert device.calls[0]["strategy"] == "text_nodes"
    assert sc.ctx["text_nodes"] == ["line"]


def test_non_fb_content_strategy_routes_to_agent_boot(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok", "platform": "tiktok"},
        },
    })

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {"collection": "social", "edge_extra_data": True},
        "tiktok_posts",
        {},
    )

    assert handled is True
    assert device.calls[0]["strategy"] == "tiktok_posts"
    assert device.calls[0]["context"]["platform"] == "tiktok"
    assert device.calls[0]["context"]["content_type"] == "tiktok_video"


def test_edge_extra_endpoint_allowlist_rejects_host_prefix_spoof(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL_ALLOWLIST", "http://agent.local:8765")

    assert extraction_mod._edge_extra_endpoint_allowed("http://agent.local:8765/extra-data/xml") is True
    assert extraction_mod._edge_extra_endpoint_allowed("http://agent.local:8765.evil.test/extra-data/xml") is False
    assert extraction_mod._edge_extra_endpoint_allowed("http://agent.local:8766/extra-data/xml") is False


def test_edge_extra_endpoint_for_device_rewrites_loopback_to_public(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("EDGE_EXTRA_AGENT_PUBLIC_URL", "http://192.168.1.50:8765")

    endpoint = extraction_mod._edge_extra_endpoint_for_device({})
    assert endpoint == "http://192.168.1.50:8765/extra-data/xml"


def test_edge_extra_endpoint_for_device_keeps_lan_url(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://192.168.1.10:8765")

    endpoint = extraction_mod._edge_extra_endpoint_for_device({})
    assert endpoint == "http://192.168.1.10:8765/extra-data/xml"


def test_tap_fb_comment_button_resolves_target_via_agent_boot(monkeypatch) -> None:
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "verified": True,
                "target": {
                    "bounds": [10, 20, 110, 60],
                    "pid": "pid-1",
                    "parent_base_hash": "base-hash",
                    "parent_id": "scoped-hash",
                    "post_key": "post-1",
                },
            },
        },
    })
    device.taps = []

    def tap(x, y):
        device.taps.append((x, y))

    device.tap = tap
    sc = _ctx(device)
    result = {}

    control_flow.handle_tap_fb_comment_button(
        sc,
        {},
        0,
        result,
    )

    assert result["tapped"] is True
    assert device.calls[0]["strategy"] == "fb_comment_target_tap"
    assert device.taps == [(60, 40)]
    assert sc.ctx["_edge_comment_parent_base_hash"] == "base-hash"
    assert sc.ctx["_active_comment_parent_hash"] == "scoped-hash"
    assert sc.ctx["_active_comment_parent_source"] == "tap_fb_comment_button"


def test_tap_fb_comment_button_preserves_post_detail_parent_hash(monkeypatch) -> None:
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "verified": True,
                "target": {
                    "bounds": [10, 20, 110, 60],
                    "pid": "pid-1",
                    "parent_base_hash": "target-base-hash",
                    "parent_id": "target-scoped-hash",
                    "post_key": "post-1",
                    "text_prefix": "target parent text",
                },
            },
        },
    })
    device.taps = []
    device.tap = lambda x, y: device.taps.append((x, y))
    sc = _ctx(device)
    sc.ctx["_active_comment_parent_hash"] = "detail-parent-hash"
    sc.ctx["_first_new_post_hash"] = "detail-parent-hash"
    sc.ctx["_active_comment_parent_source"] = "post_detail"
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {}, 0, result)

    assert result["tapped"] is True
    assert result["parent_context_preserved"] is True
    assert result["parent_id"] == "detail-parent-hash"
    assert sc.ctx["_active_comment_parent_hash"] == "detail-parent-hash"
    assert sc.ctx["_first_new_post_hash"] == "detail-parent-hash"
    assert sc.ctx["_active_comment_parent_source"] == "post_detail"
    assert "_edge_comment_parent_base_hash" not in sc.ctx
    assert sc.ctx["_fb_comment_parent_pid"] == "pid-1"


def test_tap_fb_comment_button_uses_persisted_post_dedupe_field(monkeypatch) -> None:
    device = _FakeDevice({
        "ok": True,
        "agent_tapped": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "verified": True,
                "target": {
                    "bounds": [10, 20, 110, 60],
                    "pid": "pid-1",
                    "parent_base_hash": "base-hash",
                    "parent_id": "scoped-hash",
                    "post_key": "post-1",
                },
            },
        },
    })
    sc = _ctx(device)
    sc.ctx["_fb_posts_dedupe_field"] = "post_key"
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {}, 0, result)

    assert result["tapped"] is True
    assert device.calls[0]["context"]["posts_dedupe_field"] == "post_key"


def test_tap_fb_comment_button_stores_parent_pid_in_anchor(monkeypatch) -> None:
    device = _FakeDevice({
        "ok": True,
        "agent_tapped": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "verified": True,
                "target": {
                    "bounds": [10, 20, 110, 60],
                    "pid": "pid-1",
                    "parent_id": "scoped-hash",
                    "post_key": "post-1",
                    "author": "Alice",
                    "timestamp": "1 giờ",
                    "text_prefix": "parent post text",
                },
            },
        },
    })
    sc = _ctx(device)
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {}, 0, result)

    assert sc.ctx["_active_comment_parent_anchor"] == {
        "pid": "pid-1",
        "post_key": "post-1",
        "stable_post_id": None,
        "fb_post_id": None,
        "author": "Alice",
        "timestamp": "1 giờ",
        "text_prefix": "parent post text",
    }


def test_tap_fb_comment_button_already_on_sheet_clears_existing_anchor() -> None:
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "already_on_comment_sheet",
                "verified": True,
                "target": None,
            },
        },
    })
    sc = _ctx(device)
    sc.ctx["_fb_comment_parent_pid"] = "pid-existing"
    sc.ctx["_active_comment_parent_anchor"] = {
        "pid": "pid-existing",
        "author": "Alice",
        "timestamp": "1 giờ",
        "text_prefix": "existing parent post",
    }
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {}, 0, result)

    assert result["tapped"] is True
    assert "_fb_comment_parent_pid" not in sc.ctx
    assert "_active_comment_parent_hash" not in sc.ctx
    assert "_active_comment_parent_anchor" not in sc.ctx
    assert "_active_comment_anchor_verified" not in sc.ctx


def test_tap_fb_comment_button_already_on_sheet_preserves_verified_parent_context() -> None:
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "already_on_comment_sheet",
                "verified": True,
                "target": None,
            },
        },
    })
    sc = _ctx(device)
    sc.ctx["_fb_comment_parent_pid"] = "pid-verified"
    sc.ctx["_active_comment_parent_hash"] = "scoped-parent-hash"
    sc.ctx["_active_comment_parent_source"] = "tap_fb_comment_button"
    sc.ctx["_active_comment_parent_anchor"] = {
        "pid": "pid-verified",
        "author": "Alice",
        "timestamp": "1 giờ",
        "text_prefix": "verified parent post",
    }
    sc.ctx["_active_comment_anchor_verified"] = True
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {}, 0, result)

    assert result["tapped"] is True
    assert result["parent_id"] == "scoped-parent-hash"
    assert result["parent_context_preserved"] is True
    assert result.get("parent_context_cleared") is not True
    assert sc.ctx["_fb_comment_parent_pid"] == "pid-verified"
    assert sc.ctx["_active_comment_parent_hash"] == "scoped-parent-hash"
    assert sc.ctx["_active_comment_anchor_verified"] is True


def test_tap_fb_comment_button_post_detail_precheck_skips_prescroll_on_comment_sheet() -> None:
    device = _SwipeTrackingFakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "already_on_comment_sheet",
                "verified": True,
                "target": None,
            },
        },
    })
    sc = _ctx(device)
    sc.ctx["_fb_comment_parent_pid"] = "pid-detail"
    sc.ctx["_active_comment_parent_hash"] = "detail-parent-hash"
    sc.ctx["_active_comment_parent_source"] = "post_detail"
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {"pre_scroll": True}, 0, result)

    assert result["ok"] is True
    assert result["tapped"] is True
    assert result["pre_scroll_skipped"] == "post_detail_target_precheck"
    assert result["parent_context_preserved"] is True
    assert device.swipes == []
    assert [call["strategy"] for call in device.calls] == [
        "fb_comment_target_tap",
        "fb_comment_filter_apply",
    ]


def test_tap_fb_comment_button_skips_prescroll_when_not_on_post_detail() -> None:
    device = _SwipeTrackingFakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "comment_button_not_found",
                "target": None,
            },
        },
    })
    sc = _ctx(device)
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {"pre_scroll": True}, 0, result)

    assert device.swipes == []
    assert result.get("pre_scroll_skipped") == "not_on_post_detail"


def test_tap_fb_comment_button_skips_comments_without_verified_post_detail() -> None:
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "verified": True,
                "target": {
                    "bounds": [10, 20, 110, 60],
                    "pid": "pid-1",
                    "parent_id": "scoped-hash",
                },
            },
        },
    })
    sc = _ctx(device)
    result = {}

    control_flow.handle_tap_fb_comment_button(
        sc,
        {"require_post_before_comment": True, "then": [{"type": "wait", "seconds": 0.1}]},
        0,
        result,
    )

    assert result["tapped"] is False
    assert result.get("post_not_ready") is True
    assert result["branch"] == "else"
    assert device.calls == []


def test_fb_posts_fails_when_open_post_detail_not_established(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 2,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
            "post_id_map": {
                "pid-1": "scoped-parent-1",
                "pid-2": "scoped-parent-2",
            },
        },
    })
    sc = _ctx(device)
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "open_post_before_extract": True,
            "require_open_post_detail": True,
        },
        "fb_posts",
        result,
    )

    assert handled is True
    assert result["ok"] is False
    assert "post detail not opened" in result["message"]


def test_fb_posts_remembers_parent_from_opened_post_diagnostic(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 0,
            "inserted_count": 0,
            "duplicate_count": 0,
            "diagnostic": {
                "reason_code": "comment_sheet",
                "opened_post": {
                    "pid": "pid-opened",
                    "post_key": "post-opened",
                    "author": "Alice",
                    "timestamp": "2 giờ",
                    "text_prefix": "opened body",
                },
            },
        },
    })
    sc = _ctx(device)
    result = {"ok": True}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "open_post_before_extract": True,
            "require_open_post_detail": True,
        },
        "fb_posts",
        result,
    )

    assert handled is True
    assert result["ok"] is True
    assert "post detail not opened" not in result.get("message", "")
    assert sc.ctx["_active_comment_anchor_verified"] is True
    assert sc.ctx["_fb_comment_parent_pid"] == "pid-opened"


def test_tap_fb_comment_button_skips_server_tap_when_agent_tapped(monkeypatch) -> None:
    device = _FakeDevice({
        "ok": True,
        "agent_tapped": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "verified": True,
                "target": {
                    "bounds": [10, 20, 110, 60],
                    "pid": "pid-1",
                    "parent_base_hash": "base-hash",
                    "parent_id": "scoped-hash",
                },
            },
        },
    })
    device.taps = []
    device.tap = lambda x, y: device.taps.append((x, y))
    result = {}

    control_flow.handle_tap_fb_comment_button(
        _ctx(device),
        {},
        0,
        result,
    )

    assert result["tapped"] is True
    assert result["agent_tapped"] is True
    assert device.taps == []


def test_tap_fb_comment_button_skips_then_when_verify_failed() -> None:
    device = _FakeDevice({
        "ok": True,
        "agent_tapped": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "verified": False,
                "target": {
                    "bounds": [10, 20, 110, 60],
                    "pid": "pid-1",
                },
            },
        },
    })
    sc = _ctx(device)
    result = {}
    then_ran = {"value": False}
    original_run_nested = control_flow._run_nested

    def _run_nested(sc_inner, steps):
        then_ran["value"] = True
        return {"success": True}

    control_flow._run_nested = _run_nested
    try:
        control_flow.handle_tap_fb_comment_button(
            sc,
            {"then": [{"type": "sleep", "seconds": 0.01}]},
            0,
            result,
        )
    finally:
        control_flow._run_nested = original_run_nested

    assert result["tapped"] is False
    assert result["branch"] == "else"
    assert then_ran["value"] is False
    assert "_active_comment_parent_hash" not in sc.ctx


def test_split_fb_comment_nodes_find_tap_filter_sequentially() -> None:
    device = _SequenceFakeDevice([
        {
            "ok": True,
            "ingest": {
                "diagnostic": {
                    "reason_code": "ok",
                    "target": {
                        "bounds": [10, 20, 110, 60],
                        "pid": "pid-1",
                        "parent_id": "scoped-hash",
                        "post_key": "post-1",
                    },
                },
            },
        },
        {
            "ok": True,
            "ingest": {
                "diagnostic": {
                    "reason_code": "already_on_comment_sheet",
                    "verified": True,
                    "target": None,
                },
            },
        },
        {
            "ok": True,
            "ingest": {
                "diagnostic": {
                    "reason_code": "ok",
                    "switched": True,
                    "steps": [{"phase": "select_option"}],
                },
            },
        },
    ])
    device.taps = []
    device.tap = lambda x, y: device.taps.append((x, y))
    sc = _ctx(device)

    find_result = {}
    control_flow.handle_fb_find_comment_button(sc, {}, 0, find_result)

    assert find_result["target_found"] is True
    assert device.calls[0]["strategy"] == "fb_comment_target"
    assert device.taps == []
    assert sc.ctx["_fb_comment_target"]["post_key"] == "post-1"

    tap_result = {}
    control_flow.handle_fb_tap_comment_target(sc, {}, 1, tap_result)

    assert tap_result["target_verified"] is True
    assert device.calls[1]["strategy"] == "fb_comment_target"
    assert device.taps == [(60, 40)]
    assert sc.ctx["_active_comment_parent_hash"] == "scoped-hash"
    assert sc.ctx["_active_comment_parent_source"] == "fb_tap_comment_target"
    assert "_fb_comment_target" not in sc.ctx

    filter_result = {}
    control_flow.handle_fb_apply_comment_filter(
        sc,
        {"comment_filter": "newest"},
        2,
        filter_result,
    )

    assert filter_result["filter_applied"] is True
    assert device.calls[2]["strategy"] == "fb_comment_filter_apply"
    assert device.calls[2]["context"]["comment_filter"] == "newest"
    assert sc.ctx["_fb_comment_filter_applied"] == "newest"


def test_try_edge_extra_data_prefers_scoped_parent_hash_for_comments(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    })
    sc = _ctx(device)
    sc.ctx["_edge_comment_parent_base_hash"] = "base-hash"
    sc.ctx["_active_comment_parent_hash"] = "scoped-hash"
    sc.ctx["_fb_comment_parent_pid"] = "pid-1"

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "save_parent_id_var": "_active_comment_parent_hash",
        },
        "fb_comments",
        {},
    )

    assert handled is True
    request = device.calls[-1]
    assert request["strategy"] == "fb_comments"
    assert request["context"]["parent_id"] == "scoped-hash"
    assert request["context"]["parent_id_already_scoped"] is True
    assert request["context"]["parent_post_id"] == "pid-1"


def test_try_edge_extra_data_forwards_comment_scroll_context(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}})

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "comment_scroll_passes": 4,
            "comment_scroll_distance": 0.25,
            "comment_scroll_duration_ms": 400,
            "comment_scroll_pause_s": 0.5,
            "comment_scroll_wall_s": 11,
            "stop_if_no_new": False,
            "comment_stop_if_no_new": False,
            "comment_no_new_threshold": 7,
            "no_new_threshold": 9,
        },
        "fb_comments",
        {},
    )

    assert handled is True
    request = device.calls[-1]
    assert request["strategy"] == "fb_comments"
    context = request["context"]
    assert context["comment_scroll_passes"] == 4
    assert context["comment_scroll_distance"] == 0.25
    assert context["comment_scroll_duration_ms"] == 400
    assert context["comment_scroll_pause_s"] == 0.5
    assert context["comment_scroll_wall_s"] == 11
    assert context["stop_if_no_new"] is False
    assert context["comment_stop_if_no_new"] is False
    assert context["comment_no_new_threshold"] == 7
    assert context["no_new_threshold"] == 9


def test_try_edge_extra_data_forwards_custom_comment_crawl_budget(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}})

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "extract_profile": "balanced",
            "max_items": 333,
            "comment_scroll_passes": 27,
            "comment_swipes_per_dump": 5,
            "comment_max_snapshots": 18,
            "comment_scroll_wall_s": 44,
            "comment_stop_if_no_new": False,
            "stop_if_no_new": False,
            "no_new_threshold": 6,
        },
        "fb_comments",
        {},
    )

    assert handled is True
    context = device.calls[-1]["context"]
    assert context["max_items"] == 333
    assert context["comment_scroll_passes"] == 27
    assert context["comment_swipes_per_dump"] == 5
    assert context["comment_max_snapshots"] == 18
    assert context["comment_scroll_wall_s"] == 44
    assert context["comment_stop_if_no_new"] is False
    assert context["stop_if_no_new"] is False
    assert context["no_new_threshold"] == 6


def test_try_edge_extra_data_normalizes_legacy_balanced_comment_budget(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}})

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "extract_profile": "balanced",
            "max_items": 500,
            "comment_scroll_passes": 40,
            "comment_swipes_per_dump": 6,
            "comment_scroll_distance": 0.52,
            "comment_scroll_duration_ms": 120,
            "comment_scroll_pause_s": 0.03,
            "comment_no_growth_break": 3,
            "min_comment_scan_passes": 2,
            "stop_if_no_new": False,
            "no_new_threshold": 4,
        },
        "fb_comments",
        {},
    )

    assert handled is True
    context = device.calls[-1]["context"]
    assert context["max_items"] == 500
    assert context["comment_scroll_passes"] == 16
    assert context["comment_swipes_per_dump"] == 6
    assert context["comment_scroll_wall_s"] == 16
    assert context["comment_max_snapshots"] == 10
    assert context["comment_stop_if_no_new"] is False
    assert context["stop_if_no_new"] is False
    assert context["comment_no_growth_break"] == 0


def test_try_edge_extra_data_preserves_stored_balanced_comment_tuning(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _SequenceFakeDevice([
        {
            "ok": True,
            "ingest": {
                "diagnostic": {
                    "reason_code": "already_all_comments",
                    "switched": True,
                }
            },
        },
        {"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}},
    ])

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "extract_profile": "balanced",
            "comment_scroll_passes": 16,
            "comment_swipes_per_dump": 4,
            "comment_scroll_duration_ms": 120,
            "comment_scroll_pause_s": 0.03,
        },
        "fb_comments",
        {},
    )

    assert handled is True
    fb_call = next(c for c in device.calls if c["strategy"] == "fb_comments")
    context = fb_call["context"]
    assert context["comment_scroll_passes"] == 16
    assert context["comment_swipes_per_dump"] == 4
    assert context["comment_scroll_duration_ms"] == 120
    assert context["comment_scroll_pause_s"] == 0.03


def test_try_edge_extra_data_preserves_frontend_user_scroll_edit(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _SequenceFakeDevice([
        {
            "ok": True,
            "ingest": {
                "diagnostic": {
                    "reason_code": "already_all_comments",
                    "switched": True,
                }
            },
        },
        {"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}},
    ])

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "extract_profile": "balanced",
            "max_items": 220,
            "comment_scroll_passes": 120,
            "comment_swipes_per_dump": 4,
            "comment_max_snapshots": 12,
            "comment_scroll_duration_ms": 120,
            "comment_scroll_pause_s": 0.03,
        },
        "fb_comments",
        {},
    )

    assert handled is True
    fb_call = next(c for c in device.calls if c["strategy"] == "fb_comments")
    context = fb_call["context"]
    assert context["comment_scroll_passes"] == 120
    assert context["comment_swipes_per_dump"] == 4
    assert context["comment_max_snapshots"] == 12
    assert context["comment_scroll_duration_ms"] == 120
    assert context["comment_scroll_pause_s"] == 0.03


def test_try_edge_extra_data_preserves_explicit_comment_timing(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _SequenceFakeDevice([
        {
            "ok": True,
            "ingest": {
                "diagnostic": {
                    "reason_code": "already_all_comments",
                    "switched": True,
                }
            },
        },
        {"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}},
    ])

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "extract_profile": "balanced",
            "comment_scroll_passes": 16,
            "comment_swipes_per_dump": 4,
            "comment_scroll_duration_ms": 300,
            "comment_scroll_pause_s": 0.5,
            "comment_scroll_settle_s": 0.4,
        },
        "fb_comments",
        {},
    )

    assert handled is True
    fb_call = next(c for c in device.calls if c["strategy"] == "fb_comments")
    context = fb_call["context"]
    assert context["comment_scroll_duration_ms"] == 300
    assert context["comment_scroll_pause_s"] == 0.5
    assert context["comment_scroll_settle_s"] == 0.4


def test_try_edge_extra_data_forwards_require_verified_parent(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}})

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "require_verified_parent": True,
        },
        "fb_comments",
        {},
    )

    assert handled is True
    request = device.calls[-1]
    assert request["strategy"] == "fb_comments"
    assert request["context"]["require_verified_parent"] is True


def test_fb_comments_direct_extract_does_not_auto_filter(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 2,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    })
    sc = _ctx(device)
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True},
        "fb_comments",
        result,
    )

    assert handled is True
    assert [call["strategy"] for call in device.calls] == ["fb_comments"]
    assert "comment_filter_on_extract" not in result
    assert "_fb_comment_filter_applied" not in sc.ctx
    assert result["extracted"] == 2


def test_fb_comments_explicit_filter_verify_state_does_not_block_extract(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 2,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    })
    sc = _ctx(device)
    sc.ctx["_fb_comment_filter_applied"] = "newest"
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True, "comment_filter": "newest"},
        "fb_comments",
        result,
    )

    assert handled is True
    assert [call["strategy"] for call in device.calls] == ["fb_comments"]
    assert result["extracted"] == 2
    assert sc.ctx["_fb_comment_filter_applied"] == "newest"


def test_fb_comments_does_not_request_filter_before_extract(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 2,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    })
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "comment_filter_on_extract": True,
            "comment_filter": "all_comments",
        },
        "fb_comments",
        result,
    )

    assert handled is True
    assert [call["strategy"] for call in device.calls] == ["fb_comments"]
    assert result["extracted"] == 2


def test_fb_comments_nested_extract_does_not_auto_filter(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    })
    sc = _ctx(device)
    extraction_mod.stage_comment_filter_for_post(
        sc.ctx,
        {"comment_filter": "newest", "switch_to_all_comments": True},
    )
    sc.ctx["_fb_comment_filter_applied"] = "all_comments"

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True},
        "fb_comments",
        {},
    )

    assert handled is True
    assert [call["strategy"] for call in device.calls] == ["fb_comments"]
    assert sc.ctx["_fb_comment_filter_applied"] == "all_comments"


def test_fb_comments_does_not_reapply_already_applied_filter(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "diagnostic": {"reason_code": "ok"},
        },
    })
    sc = _ctx(device)
    sc.ctx["_fb_comment_filter_applied"] = "newest"

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True, "comment_filter": "newest"},
        "fb_comments",
        result := {},
    )

    assert handled is True
    assert [call["strategy"] for call in device.calls] == ["fb_comments"]
    assert "comment_filter_on_extract" not in result
    assert sc.ctx["_fb_comment_filter_applied"] == "newest"


def test_tap_fb_comment_button_ignore_error_keeps_step_ok(monkeypatch) -> None:
    device = _FakeDevice({"ok": False, "error": "not_found"})
    result = {}

    control_flow.handle_tap_fb_comment_button(
        _ctx(device),
        {},
        0,
        result,
    )

    assert result["ok"] is True
    assert result["tapped"] is False


def test_resolve_campaign_id_for_edge_honors_explicit_none(monkeypatch) -> None:
    def _fail_if_called(_coro):
        raise AssertionError("resolve_persist_campaign_id should not run")

    monkeypatch.setattr("db.database.run_activity_coro", _fail_if_called)

    resolved = extraction_mod._resolve_campaign_id_for_edge(
        {
            "_campaign_id": None,
            "campaign_id": "stale-workflow-id",
            "_execution_id": "exec-1",
        }
    )

    assert resolved is None


def test_resolve_campaign_id_for_edge_revalidates_resolved_marker(monkeypatch) -> None:
    seen: dict[str, str | None] = {}

    async def _resolve(db, *, campaign_id, execution_id=None):
        seen["campaign_id"] = campaign_id
        seen["execution_id"] = execution_id
        return None

    monkeypatch.setattr(
        "services.content.campaign_ref.resolve_persist_campaign_id",
        _resolve,
    )

    def _run(coro):
        import asyncio

        return asyncio.run(coro)

    monkeypatch.setattr("db.database.run_activity_coro", _run)

    resolved = extraction_mod._resolve_campaign_id_for_edge(
        {
            "_campaign_id_resolved": True,
            "_campaign_id": "camp-validated",
            "campaign_id": "stale-workflow-id",
            "_execution_id": "exec-1",
        }
    )

    assert resolved is None
    assert seen == {"campaign_id": "camp-validated", "execution_id": "exec-1"}


def test_resolve_campaign_id_for_edge_resolve_failure_returns_none(monkeypatch) -> None:
    def _boom(_coro):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("db.database.run_activity_coro", _boom)

    resolved = extraction_mod._resolve_campaign_id_for_edge(
        {
            "campaign_id": "stale-workflow-id",
            "_execution_id": "exec-1",
        }
    )

    assert resolved is None
