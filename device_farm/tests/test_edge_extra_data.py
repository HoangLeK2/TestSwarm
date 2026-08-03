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


def test_try_edge_extra_data_forwards_post_open_fast_defaults(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")
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
        {
            "collection": "fb",
            "dedupe_field": "post_key",
            "edge_extra_data": True,
        },
        "fb_posts",
        {},
    )

    assert handled is True
    context = device.calls[-1]["context"]
    assert context["post_open_max_attempts"] == 1
    assert context["post_open_scan_window"] == 12
    assert context["post_open_tap_settle_s"] == 0.65
    assert context["post_open_verify_retries"] == 1
    assert context["post_open_verify_retry_pause_s"] == 0.18


def test_try_edge_extra_data_forwards_explicit_post_open_canonical_keys(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")
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
        {
            "collection": "fb",
            "dedupe_field": "post_key",
            "edge_extra_data": True,
            "post_open_max_attempts": 2,
            "post_open_scan_window": 20,
            "post_open_tap_settle_s": 0.2,
            "post_open_verify_retries": 2,
            "post_open_verify_retry_pause_s": 0.25,
        },
        "fb_posts",
        {},
    )

    assert handled is True
    context = device.calls[-1]["context"]
    assert context["post_open_max_attempts"] == 2
    assert context["post_open_scan_window"] == 20
    assert context["post_open_tap_settle_s"] == 0.2
    assert context["post_open_verify_retries"] == 2
    assert context["post_open_verify_retry_pause_s"] == 0.25


def test_try_edge_extra_data_accepts_partial_known_comment_target(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 20,
            "inserted_count": 20,
            "duplicate_count": 0,
            "diagnostic": {
                "reason_code": "partial_target",
                "comments_returned": 20,
                "comment_target": 220,
                "post_comment_count": 269,
                "coverage_ratio": 20 / 220,
                "comment_scroll_stopped_reason": "coverage_tail_no_new",
            },
        },
    })
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "max_items": 220,
            "comment_require_complete": True,
        },
        "fb_comments",
        result,
    )

    assert handled is True
    assert result.get("ok", True) is True
    assert result["partial"] is True
    assert result["extracted"] == 20
    assert result["reason_code"] == "partial_target"
    assert "partial" in result["message"]
    assert "20/220" in result["message"]
    assert "coverage_tail_no_new" in result["message"]


def test_try_edge_extra_data_fails_zero_comments_for_required_target(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 0,
            "inserted_count": 0,
            "duplicate_count": 0,
            "diagnostic": {
                "reason_code": "partial_target",
                "comments_returned": 0,
                "comment_target": 20,
                "post_comment_count": 20,
                "coverage_ratio": 0,
                "comment_scroll_stopped_reason": "coverage_tail_no_new",
            },
        },
    })
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "max_items": 20,
            "comment_require_complete": True,
        },
        "fb_comments",
        result,
    )

    assert handled is True
    assert result["ok"] is False
    assert result["extracted"] == 0
    assert result["reason_code"] == "partial_target"
    assert "0/20" in result["message"]
    assert "coverage_tail_no_new" in result["message"]


def test_try_edge_extra_data_reports_bounded_partial_without_retrying(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 20,
            "inserted_count": 20,
            "duplicate_count": 0,
            "diagnostic": {
                "reason_code": "partial_target",
                "comments_returned": 20,
                "comment_target": 220,
                "post_comment_count": 269,
                "coverage_ratio": 20 / 220,
                "comment_scroll_stopped_reason": "swipe_budget_exhausted",
            },
        },
    })
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "max_items": 220,
        },
        "fb_comments",
        result,
    )

    assert handled is True
    assert result.get("ok", True) is True
    assert result["extracted"] == 20
    assert result["reason_code"] == "partial_target"


def test_try_edge_extra_data_fails_when_opened_post_detail_is_incomplete(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 0,
            "inserted_count": 0,
            "duplicate_count": 0,
            "diagnostic": {
                "reason_code": "post_detail_incomplete",
                "posts_returned": 0,
            },
        },
    })
    result = {}
    sc = _ctx(device)
    sc.ctx.update(
        {
            "_active_comment_parent_hash": "previous-post-hash",
            "_fb_comment_parent_pid": "previous-post-pid",
            "_active_comment_parent_anchor": {
                "pid": "previous-post-pid",
                "post_key": "previous-post-key",
            },
            "_active_comment_anchor_verified": True,
            "_active_comment_parent_source": "post_detail",
            "_fb_comment_session": {"session_id": "previous-post-session"},
        }
    )

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb_group_posts",
            "content_type": "fb_post",
            "edge_extra_data": True,
            "open_post_before_extract": True,
            "expand_see_more": True,
        },
        "fb_posts",
        result,
    )

    assert handled is True
    assert result["ok"] is False
    assert result["reason_code"] == "post_detail_incomplete"
    assert "fb_posts incomplete" in result["message"]
    assert "_active_comment_parent_hash" not in sc.ctx
    assert "_fb_comment_parent_pid" not in sc.ctx
    assert "_active_comment_parent_anchor" not in sc.ctx
    assert "_active_comment_anchor_verified" not in sc.ctx
    assert "_active_comment_parent_source" not in sc.ctx
    assert "_fb_comment_session" not in sc.ctx
    assert sc.ctx["_fb_comment_target_missing"]["reason_code"] == "post_extract_pending"

    comment_result = {}
    comment_handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb_group_posts",
            "content_type": "fb_comment",
            "edge_extra_data": True,
            "max_items": 500,
        },
        "fb_comments",
        comment_result,
    )

    assert comment_handled is True
    assert comment_result["ok"] is True
    assert comment_result["skipped"] is True
    assert comment_result["comment_target_missing"] is True
    assert comment_result["comment_target_missing_detail"]["reason_code"] == "post_extract_pending"
    assert len(device.calls) == 1


def test_fb_posts_forces_root_item_level_for_malformed_step(monkeypatch) -> None:
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
        {
            "collection": "fb_group_posts",
            "content_type": "fb_post",
            "edge_extra_data": True,
            "item_level": 1,
        },
        "fb_posts",
        {},
    )

    assert handled is True
    assert device.calls[-1]["context"]["item_level"] == 0


def test_fb_comment_session_created_and_forwarded_to_comment_extract(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")
    device = _SequenceFakeDevice([
        {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
                "active_parent_post": {
                    "pid": "pid-1",
                    "parent_id": "parent-hash-1",
                    "post_key": "post-1",
                    "stable_post_id": "stable-1",
                    "author": "Alice",
                    "text_prefix": "parent post body",
                    "source": "post_detail",
                },
            },
        },
        {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
            },
        },
    ])
    sc = _ctx(device)

    extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb_group_posts",
            "dedupe_field": "post_key",
            "edge_extra_data": True,
            "open_post_before_extract": True,
        },
        "fb_posts",
        {},
    )

    session = sc.ctx.get("_fb_comment_session")
    assert isinstance(session, dict)
    assert session["parent_id"] == "parent-hash-1"
    assert session["parent_post_id"] == "pid-1"
    assert session["anchor"]["post_key"] == "post-1"
    assert session["source"] == "post_detail"

    extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb_group_posts",
            "dedupe_field": "comment_key",
            "edge_extra_data": True,
            "open_post_press_back_after_extract": True,
        },
        "fb_comments",
        {},
    )

    comment_context = device.calls[1]["context"]
    assert comment_context["_fb_comment_session"] == session
    assert comment_context["parent_id"] == "parent-hash-1"
    assert comment_context["parent_post_id"] == "pid-1"


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


def test_fb_apply_comment_filter_exposes_extra_data_timing(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_COMMENT_FILTER_AGENT_APPLY", "1")
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "switched": True,
                "reason_code": "already_on_filter",
                "steps": [{"phase": "done", "reason_code": "already_on_filter"}],
                "total_ms": 123.4,
                "dump_ms": 80.0,
                "parse_ms": 7.0,
                "click_ms": 0.0,
                "wait_ms": 12.5,
                "sleep_ms": 0.0,
                "state_verified": True,
            },
        },
        "route": "relay_u2",
        "request_id": "req-1",
    })
    sc = _ctx(device)
    sc.ctx["_active_comment_parent_hash"] = "parent-filter"
    sc.ctx["_fb_comment_parent_pid"] = "pid-filter"
    sc.ctx["_active_comment_parent_anchor"] = {"post_key": "post-filter"}
    result = {}

    control_flow.handle_fb_apply_comment_filter(
        sc,
        {"comment_filter": "newest", "comment_filter_settle_s": 0},
        0,
        result,
    )

    assert result["filter_applied"] is True
    assert result["extra_data_total_ms"] == 123.4
    assert result["extra_data_dump_ms"] == 80.0
    assert result["extra_data_parse_ms"] == 7.0
    assert result["extra_data_click_ms"] == 0.0
    assert result["extra_data_wait_ms"] == 12.5
    assert result["extra_data_sleep_ms"] == 0.0
    assert result["extra_data_steps"] == 1
    assert device.calls[0]["context"]["parent_id"] == "parent-filter"
    assert device.calls[0]["context"]["parent_post_id"] == "pid-filter"
    assert device.calls[0]["context"]["post_key"] == "post-filter"


def test_fb_apply_comment_filter_skips_settle_after_agent_verified_state(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_COMMENT_FILTER_AGENT_APPLY", "1")
    slept: list[float] = []
    monkeypatch.setattr(control_flow.time, "sleep", slept.append)
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "switched": True,
                "reason_code": "ok",
                "state_verified": True,
                "steps": [{"phase": "done", "reason_code": "already_on_filter"}],
            },
        },
    })
    sc = _ctx(device)
    result = {}

    control_flow.handle_fb_apply_comment_filter(
        sc,
        {"comment_filter": "newest", "comment_filter_settle_s": 0.45},
        0,
        result,
    )

    assert result["filter_applied"] is True
    assert slept == []


def test_fb_apply_comment_filter_skips_settle_on_noop(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_COMMENT_FILTER_AGENT_APPLY", "1")
    slept: list[float] = []
    monkeypatch.setattr(control_flow.time, "sleep", lambda seconds: slept.append(seconds))
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "switched": False,
                "reason_code": "not_comment_sheet",
                "steps": [{"phase": "done", "reason_code": "not_comment_sheet"}],
            },
        },
    })
    sc = _ctx(device)
    result = {}

    control_flow.handle_fb_apply_comment_filter(
        sc,
        {"comment_filter": "newest", "comment_filter_settle_s": 0.45},
        0,
        result,
    )

    assert result["filter_applied"] is False
    assert result["message"] == "fb_apply_comment_filter: not_comment_sheet"
    assert slept == []


def test_fb_apply_comment_filter_skips_after_comment_target_missing(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_COMMENT_FILTER_AGENT_APPLY", "1")
    device = _FakeDevice({"ok": True, "ingest": {"diagnostic": {"reason_code": "ok"}}})
    sc = _ctx(device)
    sc.ctx["_fb_comment_target_missing"] = {
        "selector": "description='Bình luận'",
        "max_swipes_effective": 8,
    }
    result = {}

    control_flow.handle_fb_apply_comment_filter(
        sc,
        {"comment_filter": "newest", "comment_filter_settle_s": 0.45},
        0,
        result,
    )

    assert result["filter_applied"] is False
    assert result["comment_target_missing"] is True
    assert result["message"] == "fb_apply_comment_filter: skipped — comment target missing"
    assert device.calls == []


def test_fb_comments_extract_skips_after_comment_target_missing(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({"ok": True, "ingest": {"parsed_count": 99}})
    sc = _ctx(device)
    sc.ctx["_fb_comment_target_missing"] = {
        "selector": "description='Bình luận'",
        "max_swipes_effective": 8,
    }
    result = {"ok": True}

    handled = extraction_mod.request_edge_extra_data(
        device=device,
        serial=sc.serial,
        ctx=sc.ctx,
        scenario=sc.scenario,
        step={"collection": "fb", "edge_extra_data": True},
        strategy="fb_comments",
        result=result,
    )

    assert handled is True
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["comment_target_missing"] is True
    assert result["message"] == "edge extra_data fb_comments: skipped — comment target missing"
    assert device.calls == []


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


def test_fb_posts_partial_parent_replaces_previous_parent_state(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _SequenceFakeDevice([
        {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
                "active_parent_post": {
                    "pid": "pid-a",
                    "parent_id": "parent-a",
                    "post_key": "post-a",
                    "author": "Alice",
                    "text_prefix": "post A body",
                    "source": "post_detail",
                },
            },
        },
        {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
                "active_parent_post": {
                    "parent_id": "parent-b",
                    "source": "post_detail",
                },
            },
        },
        {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
            },
        },
    ])
    sc = _ctx(device)
    post_step = {"collection": "fb", "edge_extra_data": True, "dedupe_field": "post_key"}

    extraction_mod._try_edge_extra_data(sc, post_step, "fb_posts", {})
    extraction_mod._try_edge_extra_data(sc, post_step, "fb_posts", {})
    extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True},
        "fb_comments",
        {},
    )

    assert sc.ctx["_active_comment_parent_hash"] == "parent-b"
    assert "_fb_comment_parent_pid" not in sc.ctx
    assert "_active_comment_parent_anchor" not in sc.ctx
    assert sc.ctx["_fb_comment_session"]["parent_id"] == "parent-b"
    assert sc.ctx["_fb_comment_session"]["parent_post_id"] is None
    comment_context = device.calls[-1]["context"]
    assert comment_context["parent_id"] == "parent-b"
    assert comment_context["parent_post_id"] is None
    assert comment_context["_active_comment_parent_anchor"] is None


def test_fb_comments_back_marks_parent_consumed_for_next_post_open(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _SequenceFakeDevice([
        {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
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
        },
        {
            "ok": True,
            "ingest": {
                "parsed_count": 0,
                "inserted_count": 0,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
            },
        },
        {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
            },
        },
    ])
    sc = _ctx(device)

    extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True, "dedupe_field": "post_key"},
        "fb_posts",
        {},
    )
    extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "open_post_press_back_after_extract": True,
        },
        "fb_comments",
        {},
    )
    extraction_mod._try_edge_extra_data(
        sc,
        {"collection": "fb", "edge_extra_data": True, "dedupe_field": "post_key"},
        "fb_posts",
        {},
    )

    assert "_active_comment_parent_anchor" not in sc.ctx
    consumed = sc.ctx["_fb_consumed_post_anchors"]
    assert consumed == [
        {
            "pid": "pid-1",
            "post_key": "post-1",
            "stable_post_id": "stable-1",
            "fb_post_id": "fb-1",
            "author": "Alice",
            "timestamp": "1 giờ",
            "text_prefix": "parent post body",
            "parent_id": "scoped-parent-hash",
        }
    ]
    assert device.calls[2]["strategy"] == "fb_posts"
    assert device.calls[2]["context"]["open_post_exclude_anchors"] == consumed


def test_fb_posts_post_open_verify_failed_in_loop_skips_without_excluding_anchor(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _SequenceFakeDevice([
        {
            "ok": False,
            "error": "post_open_required:post_open_verify_failed",
            "diagnostic": {
                "reason_code": "post_open_verify_failed",
                "attempted_open_post_anchors": [
                    {
                        "pid": "pid-1",
                        "post_key": "post-1",
                        "stable_post_id": "stable-1",
                        "author": "Alice",
                        "timestamp": "1 giờ",
                        "text_prefix": "parent post body",
                    }
                ],
            },
        },
        {
            "ok": True,
            "ingest": {
                "parsed_count": 0,
                "inserted_count": 0,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
            },
        },
    ])
    sc = _ctx(device)
    sc.ctx["_loop_iter"] = 6
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "dedupe_field": "post_key",
        },
        "fb_posts",
        result,
    )

    assert handled is True
    assert result.get("ok", True) is True
    assert result["skipped"] is True
    assert result["reason_code"] == "post_open_verify_failed"
    assert result["post_open_attempted_anchor_count"] == 1
    assert result["post_open_retryable_failure"] is True
    assert "_break" not in sc.ctx
    assert "_fb_consumed_post_anchors" not in sc.ctx

    extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "dedupe_field": "post_key",
        },
        "fb_posts",
        {},
    )

    assert "open_post_exclude_anchors" not in device.calls[1]["context"]


def test_fb_posts_post_open_verify_failed_without_anchor_breaks_loop(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({
        "ok": False,
        "error": "post_open_required:post_open_verify_failed",
        "diagnostic": {"reason_code": "post_open_verify_failed"},
    })
    sc = _ctx(device)
    sc.ctx["_loop_iter"] = 6
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "dedupe_field": "post_key",
        },
        "fb_posts",
        result,
    )

    assert handled is True
    assert result.get("ok", True) is True
    assert result["skipped"] is True
    assert sc.ctx["_break"] is True


def test_fb_posts_reconcile_failed_in_loop_skips_and_excludes_opened_anchor(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    opened_anchor = {
        "pid": "pid-1",
        "post_key": "post-1",
        "stable_post_id": "stable-1",
        "author": "Alice",
        "timestamp": "1 giờ",
        "text_prefix": "parent post body",
    }
    device = _SequenceFakeDevice([
        {
            "ok": True,
            "ingest": {
                "parsed_count": 0,
                "inserted_count": 0,
                "duplicate_count": 0,
                "diagnostic": {
                    "reason_code": "post_detail_target_not_reconciled",
                    "opened_post": opened_anchor,
                },
            },
        },
        {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
            },
        },
    ])
    sc = _ctx(device)
    sc.ctx["_loop_iter"] = 5
    result = {}

    handled = extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "dedupe_field": "post_key",
        },
        "fb_posts",
        result,
    )

    assert handled is True
    assert result.get("ok", True) is True
    assert result["skipped"] is True
    assert result["reason_code"] == "post_detail_target_not_reconciled"
    assert "_break" not in sc.ctx
    consumed = sc.ctx["_fb_consumed_post_anchors"]
    assert consumed == [opened_anchor]

    extraction_mod._try_edge_extra_data(
        sc,
        {
            "collection": "fb",
            "edge_extra_data": True,
            "dedupe_field": "post_key",
        },
        "fb_posts",
        {},
    )

    assert device.calls[1]["context"]["open_post_exclude_anchors"] == consumed


def test_fb_posts_reconcile_failed_with_opened_anchor_skips_even_without_loop_iter(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    opened_anchor = {
        "pid": "pid-1",
        "post_key": "post-1",
        "stable_post_id": "stable-1",
        "author": "Alice",
        "timestamp": "1 giờ",
        "text_prefix": "parent post body",
    }
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "parsed_count": 0,
            "inserted_count": 0,
            "duplicate_count": 0,
            "diagnostic": {
                "reason_code": "post_detail_target_not_reconciled",
                "opened_post": opened_anchor,
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
            "dedupe_field": "post_key",
        },
        "fb_posts",
        result,
    )

    assert handled is True
    assert result.get("ok", True) is True
    assert result["skipped"] is True
    assert result["reason_code"] == "post_detail_target_not_reconciled"
    assert result["post_open_consumed_anchor_count"] == 1
    assert sc.ctx["_fb_consumed_post_anchors"] == [opened_anchor]


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
    sc.ctx["_fb_comment_target_missing"] = {
        "reason_code": "scroll_target_missing",
    }
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
    assert "_fb_comment_target_missing" not in sc.ctx


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
    sc.ctx["_fb_comment_parent_pid"] = "detail-pid"
    sc.ctx["_active_comment_parent_source"] = "post_detail"
    sc.ctx["_active_comment_parent_anchor"] = {
        "pid": "detail-pid",
        "post_key": "detail-post",
        "text_prefix": "detail parent text",
    }
    sc.ctx["_active_comment_anchor_verified"] = True
    sc.ctx["_fb_comment_session"] = {
        "session_id": "detail-session",
        "parent_id": "detail-parent-hash",
        "parent_post_id": "detail-pid",
        "source": "post_detail",
        "anchor": sc.ctx["_active_comment_parent_anchor"],
    }
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {}, 0, result)

    assert result["tapped"] is True
    assert result["parent_context_preserved"] is True
    assert result["parent_id"] == "detail-parent-hash"
    assert sc.ctx["_active_comment_parent_hash"] == "detail-parent-hash"
    assert sc.ctx["_first_new_post_hash"] == "detail-parent-hash"
    assert sc.ctx["_active_comment_parent_source"] == "post_detail"
    assert "_edge_comment_parent_base_hash" not in sc.ctx
    assert sc.ctx["_fb_comment_parent_pid"] == "detail-pid"
    assert sc.ctx["_active_comment_parent_anchor"] == {
        "pid": "detail-pid",
        "post_key": "detail-post",
        "text_prefix": "detail parent text",
    }
    assert sc.ctx["_fb_comment_session"]["parent_post_id"] == "detail-pid"
    assert sc.ctx["_fb_tapped_comment_target"]["pid"] == "pid-1"


def test_tap_fb_comment_button_does_not_preserve_incomplete_post_detail_parent(monkeypatch) -> None:
    device = _FakeDevice({
        "ok": True,
        "ingest": {
            "diagnostic": {
                "reason_code": "ok",
                "verified": True,
                "target": {
                    "bounds": [10, 20, 110, 60],
                    "pid": "target-pid",
                    "parent_base_hash": "target-base-hash",
                    "parent_id": "target-scoped-hash",
                    "post_key": "target-post",
                    "text_prefix": "target parent text",
                },
            },
        },
    })
    device.taps = []
    device.tap = lambda x, y: device.taps.append((x, y))
    sc = _ctx(device)
    sc.ctx["_active_comment_parent_hash"] = "stale-detail-parent-hash"
    sc.ctx["_first_new_post_hash"] = "stale-detail-parent-hash"
    sc.ctx["_active_comment_parent_source"] = "post_detail"
    sc.ctx["_active_comment_anchor_verified"] = True
    sc.ctx["_fb_comment_session"] = {
        "session_id": "stale-session",
        "parent_id": "different-detail-parent-hash",
        "parent_post_id": "different-detail-pid",
        "source": "post_detail",
    }
    sc.ctx["_fb_tapped_comment_target"] = {
        "pid": "old-tapped-pid",
        "parent_id": "old-tapped-hash",
    }
    sc.ctx["_fb_comment_target_missing"] = {
        "reason_code": "post_extract_pending",
    }
    result = {}

    control_flow.handle_tap_fb_comment_button(sc, {}, 0, result)

    assert result["tapped"] is True
    assert result["parent_context_preserved"] is False
    assert result["parent_id"] == "target-scoped-hash"
    assert result["_pid"] == "target-pid"
    assert device.taps == [(60, 40)]
    assert sc.ctx["_edge_comment_parent_base_hash"] == "target-base-hash"
    assert sc.ctx["_active_comment_parent_hash"] == "target-scoped-hash"
    assert sc.ctx["_first_new_post_hash"] == "target-scoped-hash"
    assert sc.ctx["_fb_comment_parent_pid"] == "target-pid"
    assert sc.ctx["_active_comment_parent_source"] == "tap_fb_comment_button"
    assert sc.ctx["_active_comment_anchor_verified"] is True
    assert "_fb_comment_session" not in sc.ctx
    assert "_fb_tapped_comment_target" not in sc.ctx
    assert "_fb_comment_target_missing" not in sc.ctx


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
    sc.ctx["_active_comment_parent_anchor"] = {
        "pid": "pid-detail",
        "post_key": "detail-post",
        "text_prefix": "detail parent text",
    }
    sc.ctx["_active_comment_anchor_verified"] = True
    sc.ctx["_fb_comment_session"] = {
        "session_id": "detail-session",
        "parent_id": "detail-parent-hash",
        "parent_post_id": "pid-detail",
        "source": "post_detail",
        "anchor": sc.ctx["_active_comment_parent_anchor"],
    }
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
    sc.ctx["_fb_comment_target_missing"] = {
        "reason_code": "scroll_target_missing",
    }

    tap_result = {}
    control_flow.handle_fb_tap_comment_target(sc, {}, 1, tap_result)

    assert tap_result["target_verified"] is True
    assert device.calls[1]["strategy"] == "fb_comment_target"
    assert device.taps == [(60, 40)]
    assert sc.ctx["_active_comment_parent_hash"] == "scoped-hash"
    assert sc.ctx["_active_comment_parent_source"] == "fb_tap_comment_target"
    assert "_fb_comment_target" not in sc.ctx
    assert "_fb_comment_target_missing" not in sc.ctx

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
    sc.ctx["_fb_comment_filter_target"] = "newest"

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
    assert request["context"]["comment_filter"] == "newest"


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
    assert "comment_require_complete" not in context


def test_try_edge_extra_data_forwards_comment_fast_scroll_and_coverage_knobs(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    device = _FakeDevice({"ok": True, "ingest": {"parsed_count": 0, "inserted_count": 0}})

    handled = extraction_mod._try_edge_extra_data(
        _ctx(device),
        {
            "collection": "fb",
            "edge_extra_data": True,
            "max_items": 500,
            "comment_large_target_fast_scroll": True,
            "comment_large_target_swipes_per_dump": 12,
            "comment_large_target_scroll_distance": 0.68,
            "comment_large_target_duration_ms": 80,
            "comment_target_budget": True,
            "comment_target_comments_per_swipe": 2,
            "comment_target_budget_unknown_count": True,
            "comment_hard_budget": False,
            "lock_comment_crawl_profile": False,
            "comment_crawl_mode": "batched",
            "comment_auto_coverage": False,
            "comment_anchor_probe_count": 4,
            "comment_anchor_min_overlap": 2,
            "comment_coverage_scroll_distance": 0.42,
            "comment_coverage_min_distance": 0.18,
            "comment_coverage_gap_backoff": 0.7,
            "comment_coverage_tail_no_new_threshold": 3,
        },
        "fb_comments",
        {},
    )

    assert handled is True
    context = device.calls[-1]["context"]
    assert context["comment_large_target_fast_scroll"] is True
    assert context["comment_large_target_swipes_per_dump"] == 12
    assert context["comment_large_target_scroll_distance"] == 0.68
    assert context["comment_large_target_duration_ms"] == 80
    assert context["comment_target_budget"] is True
    assert context["comment_target_comments_per_swipe"] == 2
    assert context["comment_target_budget_unknown_count"] is True
    assert context["comment_hard_budget"] is False
    assert context["lock_comment_crawl_profile"] is False
    assert context["comment_crawl_mode"] == "batched"
    assert context["comment_auto_coverage"] is False
    assert context["comment_anchor_probe_count"] == 4
    assert context["comment_anchor_min_overlap"] == 2
    assert context["comment_coverage_scroll_distance"] == 0.42
    assert context["comment_coverage_min_distance"] == 0.18
    assert context["comment_coverage_gap_backoff"] == 0.7
    assert context["comment_coverage_tail_no_new_threshold"] == 3


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
