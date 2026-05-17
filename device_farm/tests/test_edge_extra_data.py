from __future__ import annotations

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
    )


def test_try_edge_extra_data_success(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 2,
            "inserted_count": 1,
            "duplicate_count": 1,
            "diagnostic": {"reason_code": "ok"},
            "items": [{"post_key": "p1", "text": "hello"}],
        },
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
    assert device.calls[0]["endpoint"] == "http://agent.local:8765/extra-data/xml"
    assert device.calls[0]["context"]["user_id"] == "user"
    assert device.calls[0]["token"] == "secret"
    assert device.calls[0]["context"]["persist"] is True
    assert device.calls[0]["context"]["return_items"] is False
    assert result["edge_extra_summary"]["items_omitted"] == 1
    assert "posts" not in sc.ctx


def test_try_edge_extra_data_can_return_items_when_requested(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
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


def test_try_edge_extra_data_reports_failure_without_server_fallback(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
    device = _FakeDevice({"ok": False, "error": "boom"})
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {"collection": "fb", "edge_extra_data": True},
        "fb_posts",
        result,
    )

    assert handled is True
    assert result["ok"] is False
    assert "boom" in result["message"]


def test_try_edge_extra_data_defaults_content_strategy_to_agent_boot(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
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
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
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


def test_non_fb_content_strategy_routes_to_agent_boot(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
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
    assert device.calls[0]["context"]["content_type"] == "video"


def test_edge_extra_endpoint_allowlist_rejects_host_prefix_spoof(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL_ALLOWLIST", "http://agent.local:8765")

    assert extraction_mod._edge_extra_endpoint_allowed("http://agent.local:8765/extra-data/xml") is True
    assert extraction_mod._edge_extra_endpoint_allowed("http://agent.local:8765.evil.test/extra-data/xml") is False
    assert extraction_mod._edge_extra_endpoint_allowed("http://agent.local:8766/extra-data/xml") is False


def test_tap_fb_comment_button_resolves_target_via_agent_boot(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
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
        {"edge_extra_agent_url": "http://agent.local:8765", "edge_extra_token": "secret"},
        0,
        result,
    )

    assert result["tapped"] is True
    assert device.calls[0]["strategy"] == "fb_comment_target_tap"
    assert device.taps == [(60, 40)]
    assert sc.ctx["_edge_comment_parent_base_hash"] == "base-hash"
    assert sc.ctx["_active_comment_parent_hash"] == "scoped-hash"


def test_tap_fb_comment_button_skips_server_tap_when_agent_tapped(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
    device = _FakeDevice({
        "ok": True,
        "agent_tapped": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
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
        {"edge_extra_agent_url": "http://agent.local:8765", "edge_extra_token": "secret"},
        0,
        result,
    )

    assert result["tapped"] is True
    assert result["agent_tapped"] is True
    assert device.taps == []


def test_try_edge_extra_data_uses_base_parent_hash_for_comments(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
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
    assert device.calls[0]["context"]["parent_id"] == "base-hash"
    assert device.calls[0]["context"]["parent_post_id"] == "pid-1"


def test_try_edge_extra_data_forwards_comment_scroll_context(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
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
        },
        "fb_comments",
        {},
    )

    assert handled is True
    context = device.calls[0]["context"]
    assert context["comment_scroll_passes"] == 4
    assert context["comment_scroll_distance"] == 0.25
    assert context["comment_scroll_duration_ms"] == 400
    assert context["comment_scroll_pause_s"] == 0.5


def test_tap_fb_comment_button_ignore_error_keeps_step_ok(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_AGENT_URL", "http://agent.local:8765")
    monkeypatch.setenv("EDGE_EXTRA_TOKEN", "secret")
    device = _FakeDevice({"ok": False, "error": "not_found"})
    result = {}

    control_flow.handle_tap_fb_comment_button(
        _ctx(device),
        {"edge_extra_agent_url": "http://agent.local:8765", "edge_extra_token": "secret"},
        0,
        result,
    )

    assert result["ok"] is True
    assert result["tapped"] is False
