from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


class _FakeVarContext:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def set(self, name: str, value: object) -> None:
        self.values[name] = value

    def lookup_raw(self, name: str, step_index: int = 0) -> object:
        del step_index
        return self.values.get(name)

    def resolve(self, value: object, step_index: int = 0) -> object:
        del step_index
        if not isinstance(value, str) or not value.startswith("${"):
            return value
        resolved = self.values.get(value[2:-1], value)
        if isinstance(resolved, list):
            return resolved[0]
        return resolved


class _FakeDevice:
    def __init__(self, *hierarchies: str) -> None:
        self._hierarchies = list(hierarchies)
        self.taps: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self.flows: list[tuple[str, dict, float, object, object]] = []
        self.flow_result: dict[str, object] | None = None

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        assert force_refresh is True
        if len(self._hierarchies) > 1:
            return self._hierarchies.pop(0)
        return self._hierarchies[0]

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def key(self, name: str) -> None:
        self.keys.append(name)

    def u2_flow(
        self,
        name: str,
        params: dict,
        timeout: float = 30.0,
        priority: object = None,
        deadline_ms: object = None,
    ) -> dict[str, object]:
        self.flows.append((name, params, timeout, priority, deadline_ms))
        if self.flow_result is None:
            raise RuntimeError("u2 flow not configured")
        return self.flow_result


def _xml(*nodes: str) -> str:
    return f"<hierarchy>{''.join(nodes)}</hierarchy>"


def _node(
    label: str,
    *,
    selected: bool = False,
    bounds: str = "[10,20][110,70]",
) -> str:
    return (
        f'<node text="{label}" content-desc="{label}" '
        f'clickable="true" selected="{str(selected).lower()}" '
        f'bounds="{bounds}" />'
    )


def _desc_node(
    desc: str,
    *,
    text: str = "",
    bounds: str = "[10,20][110,70]",
    clickable: bool = True,
) -> str:
    return (
        f'<node text="{text}" content-desc="{desc}" '
        f'clickable="{str(clickable).lower()}" selected="false" bounds="{bounds}" />'
    )


def _context(device: _FakeDevice) -> SimpleNamespace:
    return SimpleNamespace(
        serial="PHONE-01",
        device=device,
        cancel_event=None,
        ctx={"vars": {}},
        var_ctx=_FakeVarContext(),
        capture_dir=None,
        scenario={},
        execution_id=None,
    )


def _ledger_step() -> dict[str, object]:
    return {
        "id": "step-1",
        "account_id": "account-1",
        "type": "content_interaction",
        "platform": "facebook",
        "action": "like",
        "timeout": 0.1,
        "poll": 0.01,
        "verify_timeout": 0.1,
        "settle_seconds": 0,
    }


def test_disabled_ledger_has_zero_coordinator_behavior(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "disabled")
    monkeypatch.setattr(
        "services.account_actions.prepare_action",
        lambda **_: pytest.fail("coordinator called"),
    )
    device = _FakeDevice(_xml(_node("Like")), _xml(_node("Unlike")))

    result = dispatch_step(_context(device), _ledger_step(), 0)

    assert result["ok"] is True
    assert "account_action_ledger" not in result


def test_enabled_ledger_claims_before_tap_and_fails_closed(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "enabled")
    events: list[str] = []
    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity",
        lambda **_: {
            "account_id": "account-1",
            "execution_id": "execution-1",
            "step_id": "step-1",
        },
    )
    monkeypatch.setattr(
        "services.account_actions.prepare_action",
        lambda **_: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    device = _FakeDevice(_xml(_node("Like")))
    original_tap = device.tap
    device.tap = lambda x, y: (events.append("tap"), original_tap(x, y))

    result = dispatch_step(_context(device), _ledger_step(), 0)

    assert result["outcome"] == "ledger_prepare_failed"
    assert events == []
    assert device.taps == []


def test_observe_ledger_failure_never_changes_social_behavior(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "observe")
    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity", lambda **_: {}
    )
    monkeypatch.setattr(
        "services.account_actions.observe_action",
        lambda **_: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    device = _FakeDevice(_xml(_node("Like")), _xml(_node("Unlike")))

    result = dispatch_step(_context(device), _ledger_step(), 0)

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert device.taps == [(60, 45)]
    assert result["action_bounds"] == (10, 20, 110, 70)
    assert result["matched_label"] == "like"


def test_enabled_finalization_failure_fails_result_after_tap(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "enabled")
    events: list[str] = []
    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity", lambda **_: {}
    )
    monkeypatch.setattr(
        "services.account_actions.prepare_action",
        lambda **_: (
            events.append("prepare") or {"action_id": "action-1", "org_id": "org-1"}
        ),
    )
    monkeypatch.setattr(
        "services.account_actions.finalize_action",
        lambda **_: (
            events.append("finalize")
            or (_ for _ in ()).throw(RuntimeError("commit failed"))
        ),
    )
    device = _FakeDevice(_xml(_node("Like")), _xml(_node("Unlike")))
    original_tap = device.tap
    device.tap = lambda x, y: (events.append("tap"), original_tap(x, y))

    result = dispatch_step(_context(device), _ledger_step(), 0)

    assert events == ["prepare", "tap", "finalize"]
    assert result["ok"] is False
    assert result["outcome"] == "ledger_finalize_failed"
    assert result["action_performed"] is True


def test_tap_failure_finalizes_with_actual_action_state(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "enabled")
    finalized: dict[str, object] = {}
    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity",
        lambda **_: {
            "account_id": "account-1",
            "execution_id": "execution-1",
            "step_id": "step-1",
        },
    )
    monkeypatch.setattr(
        "services.account_actions.prepare_action",
        lambda **_: {
            "action_id": "action-1",
            "org_id": "org-1",
            "attempt_no": 1,
            "claimed": True,
        },
    )

    def capture_finalize(**kwargs):
        finalized.update(kwargs)
        return {"action_id": "action-1", "status": "failed"}

    monkeypatch.setattr("services.account_actions.finalize_action", capture_finalize)
    device = _FakeDevice(_xml(_node("Like")))
    device.tap = lambda *_: (_ for _ in ()).throw(RuntimeError("tap unavailable"))

    result = dispatch_step(_context(device), _ledger_step(), 0)

    assert result["outcome"] == "tap_failed"
    assert result["action_performed"] is False
    assert finalized["result"]["action_performed"] is False
    assert finalized["terminal"] is True


def test_retryable_failure_keeps_ledger_running_until_next_attempt(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "enabled")
    finalized: dict[str, object] = {}
    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity",
        lambda **_: {
            "account_id": "account-1",
            "execution_id": "execution-1",
            "step_id": "step-1",
        },
    )
    monkeypatch.setattr(
        "services.account_actions.prepare_action",
        lambda **_: {
            "action_id": "action-1",
            "org_id": "org-1",
            "attempt_no": 1,
            "claimed": True,
        },
    )

    def capture_finalize(**kwargs):
        finalized.update(kwargs)
        return {"action_id": "action-1", "status": "running"}

    monkeypatch.setattr("services.account_actions.finalize_action", capture_finalize)
    device = _FakeDevice(_xml(_node("Like")))
    device.tap = lambda *_: (_ for _ in ()).throw(RuntimeError("JSON-RPC HTTP 502"))
    step = {
        **_ledger_step(),
        "retry": {"max_attempts": 2, "retryable_reasons": ["u2_transient_error"]},
        "_account_action_retry_attempt": 1,
    }

    dispatch_step(_context(device), step, 0)

    assert finalized["terminal"] is False


def test_precondition_failure_is_recorded_without_claiming_action_performed(
    monkeypatch,
) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "enabled")
    finalized: dict[str, object] = {}
    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity",
        lambda **_: {
            "account_id": "account-1",
            "execution_id": "execution-1",
            "step_id": "step-1",
        },
    )
    monkeypatch.setattr(
        "services.account_actions.prepare_action",
        lambda **_: {
            "action_id": "action-1",
            "org_id": "org-1",
            "attempt_no": 1,
            "claimed": True,
        },
    )

    def capture_finalize(**kwargs):
        finalized.update(kwargs)
        return {"action_id": "action-1", "status": "failed"}

    monkeypatch.setattr("services.account_actions.finalize_action", capture_finalize)
    step = {**_ledger_step(), "platform": "unsupported-platform"}

    result = dispatch_step(_context(_FakeDevice(_xml())), step, 0)

    assert result["outcome"] == "unsupported_platform"
    assert result["action_performed"] is False
    assert finalized["reason"] == "unsupported_platform"
    assert finalized["result"]["action_performed"] is False


@pytest.mark.parametrize(
    ("step_type", "before_label", "after_label", "expected_state"),
    [
        ("content_interaction", "Thích", "Bỏ Thích", "liked"),
        ("connection_request", "Thêm bạn bè", "Hủy lời mời", "request_pending"),
        ("community_membership", "Tham gia nhóm", "Đang chờ", "join_pending"),
    ],
)
def test_social_action_taps_current_screen_and_verifies_state(
    step_type: str,
    before_label: str,
    after_label: str,
    expected_state: str,
) -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node(before_label)), _xml(_node(after_label)))
    sc = _context(device)
    step = {
        "type": step_type,
        "platform": "facebook",
        "timeout": 0.1,
        "poll": 0.01,
        "verify_timeout": 0.1,
        "settle_seconds": 0,
        "save_as": "SOCIAL_RESULT",
    }

    result = dispatch_step(sc, step, 0)

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert result["state"] == expected_state
    assert result["action_performed"] is True
    assert device.taps == [(60, 45)]
    assert device.keys == []
    assert sc.var_ctx.values["SOCIAL_RESULT"]["state"] == expected_state
    assert sc.ctx["vars"]["SOCIAL_RESULT"]["outcome"] == "applied"


def test_social_action_is_idempotent_when_membership_is_already_satisfied() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Đã tham gia")))
    result = dispatch_step(
        _context(device),
        {
            "type": "community_membership",
            "platform": "facebook",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "already_applied"
    assert result["state"] == "member"
    assert result["action_performed"] is False
    assert result["action_bounds"] == (10, 20, 110, 70)
    assert result["matched_label"] == "da tham gia"
    assert device.taps == []
    assert device.keys == []


def test_social_select_target_delegates_to_agent_boot_and_saves_target() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": True,
        "target_type": "person",
        "source": "agent_boot",
        "confidence": 95,
        "matched_keywords": ["Hoang Le"],
        "selected_bounds": [584, 512, 921, 573],
        "action_bounds": [42, 988, 655, 1114],
        "candidate_count": 1,
    }
    sc = _context(device)

    result = dispatch_step(
        sc,
        {
            "type": "social_select_target", "target_type": "person",
            "search": "Hoang Le",
            "display_name": "Hoang Le",
            "required_keywords": ["Hoang Le"],
            "timeout": 12,
            "save_as": "_people_target",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "target_verified"
    assert device.flows[0][0] == "social_select_target"
    assert device.flows[0][1]["required_keywords"] == ["Hoang Le"]
    assert sc.ctx["vars"]["_people_target"]["verified"] is True
    assert sc.var_ctx.values["_people_target"]["action_bounds"] == [42, 988, 655, 1114]
    assert sc.ctx["vars"]["PEOPLE_PROFILE_SELECTED"] is True


def test_fb_connect_visible_people_delegates_to_agent_boot_and_saves_result(
    monkeypatch,
) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "disabled")
    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": True,
        "target_type": "person",
        "source": "visible_people_surface",
        "confidence": 80,
        "target_id": "ui:candidate-1",
        "display_name": "Nguyen Van A",
        "matched_common": ["ban chung"],
        "row_text": "Nguyen Van A 3 bạn chung Thêm bạn bè",
        "action_bounds": [600, 120, 900, 200],
        "selected_tap": [750, 160],
        "candidate_count": 3,
    }
    sc = _context(device)

    result = dispatch_step(
        sc,
        {
            "type": "social_connect_visible_people",
            "platform": "facebook",
            "min_score": 40,
            "require_common": True,
            "common_keywords": ["bạn chung", "cùng nhóm"],
            "timeout": 8,
            "verify_wait_s": 0.8,
            "save_as": "_visible_connection_action",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert result["state"] == "request_pending"
    assert result["action_performed"] is True
    assert device.flows[0][0] == "social_connect_visible_people"
    assert device.flows[0][1]["common_keywords"] == ["bạn chung", "cùng nhóm"]
    assert (
        sc.var_ctx.values["_visible_connection_action"]["verified_target"]["target_id"]
        == "ui:candidate-1"
    )


def test_fb_connect_visible_people_continues_when_no_common_row(
    monkeypatch,
) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "disabled")
    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": False,
        "reason": "no_common_connectable_people",
        "candidate_count": 4,
    }
    result = dispatch_step(
        _context(device),
        {
            "type": "social_connect_visible_people",
            "platform": "facebook",
            "save_as": "_visible_connection_action",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "no_common_connectable_people"
    assert result["action_performed"] is False
    assert device.flows[0][0] == "social_connect_visible_people"


def test_fb_connect_visible_people_batch_saves_sent_counters(
    monkeypatch,
) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "disabled")
    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": True,
        "batch": True,
        "target_type": "person",
        "source": "visible_people_surface",
        "target_count": 5,
        "sent_count": 2,
        "eligible_count": 3,
        "screens_scanned": 2,
        "scrolls": 1,
        "sent": [
            {
                "verified": True,
                "target_type": "person",
                "source": "visible_people_surface",
                "confidence": 95,
                "target_id": "ui:candidate-1",
                "display_name": "Nguyen Van A",
                "matched_common": ["ban chung"],
                "mutual_count": 3,
                "row_text": "Nguyen Van A 3 bạn chung",
                "action_bounds": [600, 120, 900, 200],
            },
            {
                "verified": True,
                "target_type": "person",
                "source": "visible_people_surface",
                "confidence": 85,
                "target_id": "ui:candidate-2",
                "display_name": "Tran Van B",
                "matched_common": ["ban chung"],
                "mutual_count": 1,
                "row_text": "Tran Van B 1 bạn chung",
                "action_bounds": [600, 340, 900, 420],
            },
        ],
    }
    sc = _context(device)
    sc.var_ctx.values["CONNECTION_TARGET_COUNT"] = 5
    sc.var_ctx.values["CONNECTION_MAX_SCROLLS"] = 10

    result = dispatch_step(
        sc,
        {
            "type": "social_connect_visible_people",
            "platform": "facebook",
            "open_surface": True,
            "target_count": "${CONNECTION_TARGET_COUNT}",
            "max_scrolls": "${CONNECTION_MAX_SCROLLS}",
            "save_as": "_visible_connection_action",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert result["action_performed"] is True
    assert result["sent_count"] == 2
    assert len(result["verified_targets"]) == 2
    assert device.flows[0][1]["open_surface"] is True
    assert device.flows[0][1]["target_count"] == 5
    assert device.flows[0][1]["max_scrolls"] == 10
    saved = sc.var_ctx.values["_visible_connection_action"]
    assert saved["sent_count"] == 2
    assert saved["verified_targets"][0]["target_id"] == "ui:candidate-1"


def test_social_select_target_skips_and_defers_unverified_candidate(
    monkeypatch,
) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity",
        lambda **_kwargs: {"account_id": "account-1"},
    )
    deferred: list[dict[str, object]] = []
    monkeypatch.setattr(
        "services.candidate_runtime.defer_connection_candidate",
        lambda **kwargs: deferred.append(kwargs)
        or {
            "candidate_id": "candidate-1",
            "status": "deferred",
            "deferred": True,
        },
    )
    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": False,
        "reason": "ambiguous_target",
        "message": "multiple Facebook People rows matched required keywords",
    }
    sc = _context(device)
    sc.ctx["vars"]["TARGET_ENTITY_ID"] = "entity-1"
    sc.ctx["vars"]["CANDIDATE_LEASE_TOKEN"] = "lease-1"
    sc.var_ctx.set("TARGET_ENTITY_ID", "entity-1")
    sc.var_ctx.set("CANDIDATE_LEASE_TOKEN", "lease-1")

    result = dispatch_step(
        sc,
        {
            "type": "social_select_target", "target_type": "person",
            "search": "Nguyen Van A",
            "display_name": "Nguyen Van A",
            "required_keywords": ["Nguyen Van A"],
            "save_as": "_people_target",
            "save_success_as": "PEOPLE_PROFILE_SELECTED",
            "skip_candidate_on_not_verified": True,
            "candidate_entity_id": "${TARGET_ENTITY_ID}",
            "candidate_lease_token": "${CANDIDATE_LEASE_TOKEN}",
            "skip_candidate_defer_hours": 24,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "candidate_skipped"
    assert sc.ctx["vars"]["PEOPLE_PROFILE_SELECTED"] is False
    assert sc.ctx["vars"]["_people_target"]["verified"] is False
    assert deferred[0]["external_entity_id"] == "entity-1"
    assert deferred[0]["lease_token"] == "lease-1"


def test_social_select_target_delegates_to_agent_boot_and_saves_target() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": True,
        "target_type": "post",
        "source": "agent_boot",
        "confidence": 94,
        "matched_keywords": ["launch text"],
        "selected_bounds": [105, 840, 1155, 1320],
        "action_bounds": [42, 1505, 227, 1659],
        "candidate_count": 1,
    }
    sc = _context(device)
    sc.ctx["vars"]["TARGET_ENTITY_ID"] = "stale-person-entity"
    sc.var_ctx.set("TARGET_ENTITY_ID", "post-entity-1")

    result = dispatch_step(
        sc,
        {
            "type": "social_select_target", "target_type": "post",
            "search": "launch text",
            "display_text": "launch text",
            "required_keywords": ["launch text"],
            "current_detail": True,
            "timeout": 12,
            "save_as": "_post_target",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "target_verified"
    assert device.flows[0][0] == "social_select_target"
    assert device.flows[0][1]["required_keywords"] == ["launch text"]
    assert device.flows[0][1]["current_detail"] is True
    assert sc.ctx["vars"]["_post_target"]["verified"] is True
    assert sc.ctx["vars"]["_post_target"]["target_id"] == "post-entity-1"
    assert sc.var_ctx.values["_post_target"]["target_type"] == "post"


def test_fb_scan_posts_interact_delegates_to_agent_boot() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": True,
        "batch": True,
        "target_type": "post",
        "interacted_count": 2,
        "liked_count": 2,
        "commented_count": 2,
        "candidate_count": 3,
        "screens_scanned": 2,
        "scrolls": 1,
        "actions": [{"target_id": "ui_post:1"}, {"target_id": "ui_post:2"}],
    }
    sc = _context(device)
    sc.var_ctx.set("POST_KEYWORDS", ["AI", "tuyển dụng"])
    sc.var_ctx.set("COMMENT_TEXT", "Bài viết hữu ích")

    result = dispatch_step(
        sc,
        {
            "type": "social_scan_posts_interact",
            "keywords": "${POST_KEYWORDS}",
            "keywords_var": "POST_KEYWORDS",
            "comment_text": "${COMMENT_TEXT}",
            "target_count": 2,
            "max_scrolls": 4,
            "save_as": "_post_scan",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert result["interacted_count"] == 2
    assert result["liked_count"] == 2
    assert result["commented_count"] == 2
    assert device.flows[0][0] == "social_scan_posts_interact"
    assert device.flows[0][1]["keywords"] == ["AI", "tuyển dụng"]
    assert device.flows[0][1]["comment_text"] == "Bài viết hữu ích"
    assert device.flows[0][1]["target_count"] == 2
    assert device.flows[0][1]["max_scrolls"] == 4
    assert device.flows[0][1]["like_post"] is True
    assert sc.ctx["vars"]["_post_scan"]["interacted_count"] == 2


def test_fb_scan_posts_interact_resolves_runtime_variable_fields() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": False,
        "batch": True,
        "reason": "no_matching_post",
        "message": "no visible Facebook post matched configured keywords",
        "interacted_count": 0,
        "candidate_count": 0,
        "screens_scanned": 36,
        "scrolls": 35,
    }
    sc = _context(device)
    sc.var_ctx.set("POST_KEYWORDS", ["AI", "MCP"])
    sc.var_ctx.set("COMMENT_TEXT", "Bài viết hữu ích")
    sc.var_ctx.set("POST_TARGET_COUNT", 3)
    sc.var_ctx.set("MAX_SCROLLS", 35)
    sc.var_ctx.set("POST_SCAN_TIMEOUT_SECONDS", 360)
    sc.var_ctx.set("POST_MATCH_MODE", "all")
    sc.var_ctx.set("SCROLL_X_RATIO", 0.42)

    result = dispatch_step(
        sc,
        {
            "type": "social_scan_posts_interact",
            "keywords_var": "POST_KEYWORDS",
            "comment_text": "${COMMENT_TEXT}",
            "target_count_var": "POST_TARGET_COUNT",
            "max_scrolls_var": "MAX_SCROLLS",
            "scan_timeout_seconds_var": "POST_SCAN_TIMEOUT_SECONDS",
            "match_mode_var": "POST_MATCH_MODE",
            "scroll_x_ratio_var": "SCROLL_X_RATIO",
        },
        0,
    )

    flow_name, params, timeout, priority, _deadline_ms = device.flows[0]
    assert result["ok"] is True
    assert flow_name == "social_scan_posts_interact"
    assert priority == "visible"
    assert timeout == 360
    assert params["keywords"] == ["AI", "MCP"]
    assert params["comment_text"] == "Bài viết hữu ích"
    assert params["target_count"] == 3
    assert params["max_scrolls"] == 35
    assert params["scan_timeout_seconds"] == 360
    assert params["match_mode"] == "all"
    assert params["scroll_x_ratio"] == 0.42


def test_fb_scan_posts_interact_no_match_is_non_terminal() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": False,
        "batch": True,
        "reason": "no_matching_post",
        "message": "no visible Facebook post matched configured keywords",
        "interacted_count": 0,
        "candidate_count": 0,
        "screens_scanned": 3,
        "scrolls": 2,
    }

    result = dispatch_step(
        _context(device),
        {
            "type": "social_scan_posts_interact",
            "keywords": ["AI"],
            "comment_text": "Bài viết hữu ích",
            "target_count": 1,
            "max_scrolls": 2,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "no_matching_post"
    assert result["action_performed"] is False
    assert result["screens_scanned"] == 3


def test_social_open_author_from_post_match_delegates_and_saves_target() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": True,
        "target_type": "person",
        "source": "matched_feed_post_author",
        "confidence": 95,
        "target_id": "ui_author:abc",
        "display_name": "Nguyen Van A",
        "matched_keywords": ["AI"],
        "selected_bounds": [210, 452, 576, 518],
        "action_bounds": [600, 720, 980, 810],
        "profile_opened": True,
        "source_post_target_id": "ui_post:abc",
    }
    sc = _context(device)
    sc.var_ctx.set(
        "_post_scan",
        {
            "actions": [
                {
                    "verified": True,
                    "target_id": "ui_post:abc",
                    "author_label": "Nguyen Van A",
                    "author_tap": [393, 485],
                    "like_bounds": [0, 1505, 223, 1659],
                    "comment_bounds": [227, 1505, 457, 1659],
                    "matched_keywords": ["AI"],
                }
            ]
        },
    )

    result = dispatch_step(
        sc,
        {
            "type": "social_open_author_from_post_match",
            "platform": "facebook",
            "source_var": "_post_scan",
            "action_index": 0,
            "required_keywords": ["AI"],
            "save_as": "_people_target",
            "save_success_as": "PEOPLE_PROFILE_SELECTED",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "target_verified"
    assert device.flows[0][0] == "social_open_author_from_post_match"
    assert device.flows[0][1]["platform"] == "facebook"
    assert device.flows[0][1]["action"]["target_id"] == "ui_post:abc"
    assert device.flows[0][1]["required_keywords"] == ["AI"]
    assert sc.ctx["vars"]["_people_target"]["verified"] is True
    assert sc.ctx["vars"]["PEOPLE_PROFILE_SELECTED"] is True
    assert sc.ctx["vars"]["AUTHOR_PROFILE_OPENED"] is True


def test_social_open_commenter_from_post_match_delegates_and_saves_target() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml())
    device.flow_result = {
        "verified": True,
        "target_type": "person",
        "source": "matched_feed_post_commenter",
        "confidence": 92,
        "target_id": "ui_commenter:abc",
        "display_name": "Tran Van B",
        "matched_keywords": ["AI"],
        "selected_bounds": [180, 740, 420, 790],
        "action_bounds": [600, 720, 980, 810],
        "profile_opened": True,
        "comment_sheet_opened": True,
        "source_post_target_id": "ui_post:abc",
    }
    sc = _context(device)
    sc.var_ctx.set(
        "_post_scan",
        {
            "actions": [
                {
                    "verified": True,
                    "target_id": "ui_post:abc",
                    "comment_bounds": [227, 1505, 457, 1659],
                    "matched_keywords": ["AI"],
                }
            ]
        },
    )

    result = dispatch_step(
        sc,
        {
            "type": "social_open_commenter_from_post_match",
            "platform": "facebook",
            "source_var": "_post_scan",
            "action_index": 0,
            "required_keywords": ["AI"],
            "max_commenters": 5,
            "save_as": "_people_target",
            "save_success_as": "PEOPLE_PROFILE_SELECTED",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "target_verified"
    assert device.flows[0][0] == "social_open_commenter_from_post_match"
    assert device.flows[0][1]["action"]["target_id"] == "ui_post:abc"
    assert device.flows[0][1]["max_commenters"] == 5
    assert sc.ctx["vars"]["_people_target"]["verified"] is True
    assert sc.ctx["vars"]["PEOPLE_PROFILE_SELECTED"] is True
    assert sc.ctx["vars"]["COMMENTER_PROFILE_OPENED"] is True
    assert sc.ctx["vars"]["COMMENT_SHEET_OPENED"] is True


def test_social_open_author_from_post_match_skips_missing_action_index() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml())
    sc = _context(device)
    sc.var_ctx.set("_post_scan", {"actions": []})

    result = dispatch_step(
        sc,
        {
            "type": "social_open_author_from_post_match",
            "platform": "facebook",
            "source_var": "_post_scan",
            "action_index": 1,
            "save_as": "_people_target",
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "source_action_index_missing"
    assert result["action_performed"] is False
    assert device.flows == []
    assert sc.ctx["vars"]["_people_target"]["verified"] is False


def test_social_action_requires_verified_target_before_tapping() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Thêm bạn bè")))
    result = dispatch_step(
        _context(device),
        {
            "type": "connection_request",
            "platform": "facebook",
            "action": "request",
            "timeout": 0.1,
            "poll": 0.01,
            "require_verified_target": "_people_target",
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "target_not_verified"
    assert device.taps == []


def test_social_action_uses_verified_target_gate_when_present() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Thêm bạn bè")), _xml(_node("Hủy lời mời")))
    sc = _context(device)
    sc.ctx["vars"]["_people_target"] = {
        "verified": True,
        "target_type": "person",
        "source": "agent_boot",
        "confidence": 95,
    }

    result = dispatch_step(
        sc,
        {
            "type": "connection_request",
            "platform": "facebook",
            "action": "request",
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.1,
            "settle_seconds": 0,
            "require_verified_target": "_people_target",
        },
        0,
    )

    assert result["ok"] is True
    assert result["verified_target"]["name"] == "_people_target"
    assert device.taps == [(60, 45)]


def test_social_action_rejects_unknown_platform_without_touching_device() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Like")))
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "unsupported-platform",
            "action": "like",
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "unsupported_platform"
    assert device.taps == []


def test_social_action_fails_closed_when_post_state_cannot_be_verified() -> None:
    from tasks.scenario.steps import dispatch_step

    unchanged = _xml(_node("Like"))
    device = _FakeDevice(unchanged, unchanged)
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "like",
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.02,
            "settle_seconds": 0,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "verification_failed"
    assert result["action_performed"] is True
    assert device.taps == [(60, 45)]


def test_social_action_adapter_registry_can_add_future_platforms() -> None:
    from services.social_actions import (
        get_social_action_adapter,
        register_social_action_adapter,
        unregister_social_action_adapter,
    )
    from services.social_actions.contract import SocialActionObservation

    class _FutureAdapter:
        platform = "future-network"

        def observe(self, **_: object) -> SocialActionObservation:
            return SocialActionObservation(state="connected")

    adapter = _FutureAdapter()
    register_social_action_adapter(adapter)
    try:
        assert get_social_action_adapter("FUTURE-NETWORK") is adapter
    finally:
        unregister_social_action_adapter(adapter.platform)


def test_social_action_fails_closed_when_multiple_targets_are_visible() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(
        _xml(
            _node("Like", bounds="[10,20][110,70]"),
            _node("Like", bounds="[10,220][110,270]"),
        )
    )
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "like",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "ambiguous_target"
    assert device.taps == []


def test_social_action_verifies_state_near_the_tapped_target() -> None:
    from tasks.scenario.steps import dispatch_step

    unrelated_liked = _node("Unlike", bounds="[10,20][110,70]")
    target_before = _node("Like", bounds="[10,220][110,270]")
    target_after = _node("Unlike", bounds="[10,220][110,270]")
    device = _FakeDevice(
        _xml(unrelated_liked, target_before),
        _xml(unrelated_liked, target_after),
    )

    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "like",
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.1,
            "settle_seconds": 0,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert device.taps == [(60, 245)]


@pytest.mark.parametrize(
    ("action", "before_label", "after_label", "expected_state"),
    [
        ("comment", "Bình luận", "Viết bình luận", "comment_opened"),
        ("share", "Chia sẻ", "Chia sẻ ngay", "share_opened"),
    ],
)
def test_content_interaction_supports_comment_and_share_actions(
    action: str,
    before_label: str,
    after_label: str,
    expected_state: str,
) -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node(before_label)), _xml(_node(after_label)))
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": action,
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.1,
            "settle_seconds": 0,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert result["state"] == expected_state
    assert device.taps == [(60, 45)]


def test_comment_completion_fails_closed_when_submit_steps_are_missing() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Bình luận")))
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "comment",
            "require_completion": True,
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "completion_not_configured"
    assert device.taps == []


def test_comment_completion_requires_post_submit_verification() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Bình luận")))
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "comment",
            "require_completion": True,
            "completion_steps": [{"type": "key", "key": "enter"}],
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "completion_not_configured"
    assert device.taps == []
    assert device.keys == []


def test_comment_completion_runs_submit_steps_before_reporting_success() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Bình luận")), _xml(_node("Viết bình luận")))
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "comment",
            "require_completion": True,
            "completion_steps": [{"type": "key", "key": "enter"}],
            "completion_verify": {"type": "key", "key": "home"},
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.1,
            "settle_seconds": 0,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert result["state"] == "comment_submitted"
    assert result["completion_results"][0]["ok"] is True
    assert device.keys == ["enter", "home"]


def test_connection_request_does_not_bulk_tap_search_results() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(
        _xml(
            _node("Thêm bạn bè", bounds="[500,120][700,170]"),
            _node("Thêm bạn bè", bounds="[500,220][700,270]"),
        )
    )
    result = dispatch_step(
        _context(device),
        {
            "type": "connection_request",
            "platform": "facebook",
            "action": "request",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "ambiguous_target"
    assert device.taps == []


def test_connection_request_checks_account_candidate_before_tap(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    checked: list[dict[str, object]] = []
    monkeypatch.setattr(
        "services.candidate_runtime.assert_connection_candidate_allowed",
        lambda **kwargs: checked.append(kwargs) or {"status": "ready_to_connect"},
    )
    device = _FakeDevice(
        _xml(_node("Thêm bạn bè")),
        _xml(_node("Hủy lời mời")),
    )
    context = _context(device)
    context.ctx["vars"]["__ACCOUNT_ID__"] = "account-1"
    result = dispatch_step(
        context,
        {
            "id": "connect-approved",
            "type": "connection_request",
            "candidate_entity_id": "entity-1",
            "require_candidate_status": "ready_to_connect",
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.1,
            "settle_seconds": 0,
        },
        0,
    )

    assert result["ok"] is True
    assert checked[0]["external_entity_id"] == "entity-1"
    assert checked[0]["allowed_statuses"] == ("ready_to_connect",)
    assert device.taps == [(60, 45)]


def test_lease_connection_candidate_sets_branch_variables(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity",
        lambda **_kwargs: {"account_id": "account-1"},
    )
    monkeypatch.setattr(
        "services.candidate_runtime.lease_connection_candidate",
        lambda **_kwargs: {
            "available": True,
            "outcome": "leased",
            "candidate_id": "candidate-1",
            "external_entity_id": "entity-1",
            "external_id": "fb-1",
            "display_name": "Nguyen Van A",
            "canonical_url": "https://facebook.example/profile",
            "lease_token": "lease-1",
            "discovery_requested": False,
        },
    )
    context = _context(_FakeDevice("<hierarchy/>"))
    result = dispatch_step(
        context,
        {"id": "lease-candidate", "type": "lease_connection_candidate"},
        0,
    )

    assert result["ok"] is True
    assert context.ctx["vars"]["CANDIDATE_AVAILABLE"] is True
    assert context.ctx["vars"]["CANDIDATE_ENTITY_ID"] == "entity-1"
    assert context.ctx["vars"]["CANDIDATE_NAME"] == "Nguyen Van A"
    assert context.ctx["vars"]["TARGET_ENTITY_ID"] == "entity-1"
    assert context.ctx["vars"]["CANDIDATE_LEASE_TOKEN"] == "lease-1"


def test_lease_source_target_sets_short_search_variable(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setattr(
        "services.account_actions.resolve_action_identity",
        lambda **_kwargs: {"account_id": "account-1"},
    )
    monkeypatch.setattr(
        "services.account_target_runtime.lease_account_target_blocking",
        lambda **_kwargs: {
            "available": True,
            "outcome": "leased",
            "account_action_id": "action-1",
            "external_entity_id": "post-1",
            "external_id": "fb-post-1",
            "display_name": "Mot bai viet dai ve tu dong hoa va cong nghe",
            "target_search_text": "Mot bai viet dai",
            "canonical_url": "https://facebook.example/posts/1",
            "entity_type": "post",
            "platform": "facebook",
        },
    )
    context = _context(_FakeDevice("<hierarchy/>"))
    result = dispatch_step(
        context,
        {"id": "lease-target", "type": "lease_source_target"},
        0,
    )

    assert result["ok"] is True
    assert context.ctx["vars"]["TARGET_NAME"] == (
        "Mot bai viet dai ve tu dong hoa va cong nghe"
    )
    assert context.ctx["vars"]["TARGET_SEARCH_TEXT"] == "Mot bai viet dai"


def test_connection_request_completes_candidate_lease_after_verified_tap(
    monkeypatch,
) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setattr(
        "services.candidate_runtime.assert_connection_candidate_allowed",
        lambda **_kwargs: {
            "candidate_id": "candidate-1",
            "status": "ready_to_connect",
        },
    )
    completed: list[dict[str, object]] = []
    monkeypatch.setattr(
        "services.candidate_runtime.complete_connection_candidate",
        lambda **kwargs: completed.append(kwargs)
        or {"candidate_id": "candidate-1", "status": "request_pending"},
    )
    device = _FakeDevice(
        _xml(_node("Thêm bạn bè")),
        _xml(_node("Hủy lời mời")),
    )
    context = _context(device)
    context.ctx["vars"]["__ACCOUNT_ID__"] = "account-1"
    result = dispatch_step(
        context,
        {
            "id": "connect-leased",
            "type": "connection_request",
            "candidate_entity_id": "entity-1",
            "candidate_lease_token": "lease-1",
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.1,
            "settle_seconds": 0,
        },
        0,
    )

    assert result["ok"] is True
    assert completed == [
        {
            "identity": completed[0]["identity"],
            "candidate_id": "candidate-1",
            "lease_token": "lease-1",
        }
    ]


def test_connection_request_completes_candidate_lease_when_already_pending(
    monkeypatch,
) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setattr(
        "services.candidate_runtime.assert_connection_candidate_allowed",
        lambda **_kwargs: {
            "candidate_id": "candidate-1",
            "status": "ready_to_connect",
        },
    )
    completed: list[dict[str, object]] = []
    monkeypatch.setattr(
        "services.candidate_runtime.complete_connection_candidate",
        lambda **kwargs: completed.append(kwargs)
        or {"candidate_id": "candidate-1", "status": "request_pending"},
    )
    context = _context(_FakeDevice(_xml(_node("Hủy yêu cầu"))))
    context.ctx["vars"]["__ACCOUNT_ID__"] = "account-1"

    result = dispatch_step(
        context,
        {
            "id": "connect-already-pending",
            "type": "connection_request",
            "candidate_entity_id": "entity-1",
            "candidate_lease_token": "lease-1",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "already_applied"
    assert result["state"] == "request_pending"
    assert completed[0]["candidate_id"] == "candidate-1"
    assert completed[0]["lease_token"] == "lease-1"


def test_connection_request_rejects_lease_without_candidate_before_tap() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Thêm bạn bè")))
    result = dispatch_step(
        _context(device),
        {
            "id": "connect-invalid-lease",
            "type": "connection_request",
            "candidate_lease_token": "lease-1",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "candidate_contract_invalid"
    assert device.taps == []


def test_connection_request_releases_lease_when_target_fails_before_tap(
    monkeypatch,
) -> None:
    from tasks.scenario.steps import dispatch_step

    monkeypatch.setattr(
        "services.candidate_runtime.assert_connection_candidate_allowed",
        lambda **_kwargs: {
            "candidate_id": "candidate-1",
            "status": "ready_to_connect",
        },
    )
    released: list[dict[str, object]] = []
    monkeypatch.setattr(
        "services.candidate_runtime.release_connection_candidate",
        lambda **kwargs: released.append(kwargs) or {"released": True},
    )
    device = _FakeDevice(_xml(_node("Thêm bạn bè")))
    context = _context(device)
    context.ctx["vars"]["__ACCOUNT_ID__"] = "account-1"
    result = dispatch_step(
        context,
        {
            "id": "connect-unverified",
            "type": "connection_request",
            "candidate_entity_id": "entity-1",
            "candidate_lease_token": "lease-1",
            "require_verified_target": "missing_target",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "target_not_verified"
    assert released[0]["external_entity_id"] == "entity-1"
    assert released[0]["lease_token"] == "lease-1"
    assert device.taps == []


def test_connection_request_rejects_unapproved_account_candidate(monkeypatch) -> None:
    from tasks.scenario.steps import dispatch_step

    def reject_candidate(**_kwargs):
        raise ValueError("candidate status approved is not ready")

    monkeypatch.setattr(
        "services.candidate_runtime.assert_connection_candidate_allowed",
        reject_candidate,
    )
    device = _FakeDevice(_xml(_node("Thêm bạn bè")))
    context = _context(device)
    context.ctx["vars"]["__ACCOUNT_ID__"] = "account-1"
    result = dispatch_step(
        context,
        {
            "id": "connect-unapproved",
            "type": "connection_request",
            "candidate_entity_id": "entity-1",
            "require_candidate_status": "ready_to_connect",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "candidate_not_approved"
    assert device.taps == []


def test_facebook_adapter_matches_live_button_prefixed_labels_without_comment_like() -> (
    None
):
    from services.social_actions.facebook import FacebookSocialActionAdapter

    xml = _xml(
        _desc_node(
            "Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận.",
            bounds="[0,1755][254,1909]",
        ),
        _desc_node(
            "Nút Chia sẻ. Nhấn đúp để chia sẻ bài viết.",
            bounds="[483,1755][715,1909]",
        ),
        _desc_node(
            "Nút Thích bình luận của Triệu. Nhấn đúp và giữ để hiển thị khay cảm xúc.",
            text="Nút Thích bình luận của Triệu. Nhấn đúp và giữ để hiển thị khay cảm xúc.",
            bounds="[1120,2077][1232,2182]",
        ),
    )
    adapter = FacebookSocialActionAdapter()

    like = adapter.observe(
        action_type="content_interaction",
        action="like",
        hierarchy_xml=xml,
    )
    share = adapter.observe(
        action_type="content_interaction",
        action="share",
        hierarchy_xml=xml,
    )

    assert like.state == "available"
    assert like.target_bounds == (0, 1755, 254, 1909)
    assert (
        like.matched_label
        == "nut thich. hay nhan dup va giu de bay to cam xuc ve binh luan."
    )
    assert share.state == "available"
    assert share.target_bounds == (483, 1755, 715, 1909)


def test_facebook_adapter_recognizes_live_pressed_like_label() -> None:
    from services.social_actions.facebook import FacebookSocialActionAdapter

    xml = _xml(
        _desc_node(
            "Đã nhấn nút Thích. Nhấn đúp và giữ để thay đổi cảm xúc.",
            bounds="[0,2182][269,2336]",
        )
    )

    observed = FacebookSocialActionAdapter().observe(
        action_type="content_interaction",
        action="like",
        hierarchy_xml=xml,
    )

    assert observed.state == "liked"
    assert observed.satisfied is True


def test_facebook_adapter_matches_button_prefixed_friend_request_states() -> None:
    from services.social_actions.facebook import FacebookSocialActionAdapter

    adapter = FacebookSocialActionAdapter()
    available = adapter.observe(
        action_type="connection_request",
        action="request",
        hierarchy_xml=_xml(_desc_node("Nút Thêm bạn bè", bounds="[500,120][700,170]")),
    )
    pending = adapter.observe(
        action_type="connection_request",
        action="request",
        hierarchy_xml=_xml(_desc_node("Nút Hủy lời mời.", bounds="[500,120][700,170]")),
    )
    pending_live_locale = adapter.observe(
        action_type="connection_request",
        action="request",
        hierarchy_xml=_xml(_desc_node("Hủy yêu cầu", bounds="[500,120][700,170]")),
    )

    assert available.state == "available"
    assert available.target_bounds == (500, 120, 700, 170)
    assert pending.state == "request_pending"
    assert pending.is_satisfied is True
    assert pending_live_locale.state == "request_pending"
    assert pending_live_locale.is_satisfied is True


def test_facebook_adapter_prefers_clickable_pending_button_over_text_child() -> None:
    from services.social_actions.facebook import FacebookSocialActionAdapter

    xml = _xml(
        _desc_node("Hủy yêu cầu", bounds="[42,935][643,1061]"),
        _desc_node(
            "Hủy yêu cầu",
            text="Hủy yêu cầu",
            bounds="[231,965][532,1032]",
            clickable=False,
        ),
    )

    pending = FacebookSocialActionAdapter().observe(
        action_type="connection_request",
        action="request",
        hierarchy_xml=xml,
        near_bounds=(42, 935, 643, 1061),
    )

    assert pending.state == "request_pending"
    assert pending.target_bounds == (42, 935, 643, 1061)
    assert pending.is_satisfied is True


def test_connection_request_prefers_clickable_profile_button_over_child_text() -> None:
    from services.social_actions.facebook import FacebookSocialActionAdapter

    xml = _xml(
        _desc_node("Thêm bạn bè", bounds="[42,988][655,1114]"),
        _desc_node(
            "Thêm bạn bè",
            text="Thêm bạn bè",
            bounds="[225,1018][550,1085]",
            clickable=False,
        ),
        _desc_node(
            "Bạn bè", text="Bạn bè", bounds="[42,1874][239,1920]", clickable=False
        ),
    )

    result = FacebookSocialActionAdapter().observe(
        action_type="connection_request",
        action="request",
        hierarchy_xml=xml,
    )

    assert result.state == "available"
    assert result.target_bounds == (42, 988, 655, 1114)


def test_social_action_failure_includes_hierarchy_dump_without_leaking_to_saved_vars(
    tmp_path: Path,
) -> None:
    from tasks.scenario.steps import dispatch_step

    xml = _xml(_node("Không phải action"))
    device = _FakeDevice(xml)
    sc = _context(device)
    sc.capture_dir = str(tmp_path)

    result = dispatch_step(
        sc,
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "share",
            "timeout": 0.1,
            "poll": 0.01,
            "save_as": "SOCIAL_RESULT",
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "target_not_found"
    assert result["observation_state"] == "not_found"
    assert result["debug_hierarchy_phase"] == "before"
    assert result["debug_hierarchy_xml"] == xml
    dump_path = Path(result["debug_hierarchy_path"])
    assert dump_path.parent == tmp_path
    assert dump_path.read_text(encoding="utf-8") == xml
    assert "debug_hierarchy_xml" not in sc.var_ctx.values["SOCIAL_RESULT"]
