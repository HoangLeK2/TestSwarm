from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.execution import recovery_runner
from services.execution.incident_detection import ScreenSnapshot, detect_incident
from services.execution.recovery_runner import maybe_recover_step
from services.execution.recovery_policy import (
    RecoveryPolicyError,
    dump_recovery_policy,
    parse_recovery_policy,
    validate_recovery_policy_shape,
)
from tasks.scenario.steps.composition import handle_run_scenario


def test_recovery_policy_accepts_ui_rule_shape():
    raw = {
        "enabled": True,
        "rules": [
            {
                "incident_type": "app_popup",
                "scope": {"step_type_any": ["content_comment"]},
                "scenario_id": "scenario-1",
                "outcome": "retry_step",
                "max_attempts": 2,
                "success_check": {"require_post_detail": True},
            }
        ],
    }

    policy = validate_recovery_policy_shape(raw)

    assert policy.enabled is True
    assert policy.rules[0].incident_types == ("app_popup",)
    assert policy.rules[0].scope["step_type_any"] == ["content_comment"]
    assert policy.rules[0].on_success == "retry_step"
    assert policy.rules[0].success_checks[0].type == "post_detail_visible"

    dumped = dump_recovery_policy(raw)
    assert dumped["rules"][0]["incident_type"] == "app_popup"
    assert dumped["rules"][0]["scope"]["step_type_any"] == ["content_comment"]
    assert dumped["rules"][0]["outcome"] == "retry_step"
    assert dumped["rules"][0]["success_check"]["require_post_detail"] is True


def test_recovery_policy_rejects_enabled_rule_without_scenario():
    with pytest.raises(RecoveryPolicyError):
        validate_recovery_policy_shape(
            {
                "enabled": True,
                "rules": [{"scope": {"step_type_any": ["content_comment"]}}],
            }
        )


def test_recovery_policy_does_not_require_incident_type():
    policy = validate_recovery_policy_shape(
        {
            "enabled": True,
            "rules": [
                {
                    "scope": {"step_type_any": ["content_comment"]},
                    "scenario_id": "recovery-1",
                }
            ],
        }
    )

    assert policy.rules[0].incident_types == ("unknown",)
    assert policy.rules[0].scope["step_type_any"] == ["content_comment"]


def test_recovery_policy_accepts_shared_campaign_rule_shape():
    policy = validate_recovery_policy_shape(
        {
            "enabled": True,
            "rules": [
                {
                    "scenario_id": "recovery-shared",
                    "outcome": "retry_step",
                    "max_attempts": 3,
                }
            ],
        }
    )

    assert policy.enabled is True
    assert policy.rules[0].incident_types == ("unknown",)
    assert policy.rules[0].scope == {}
    assert policy.rules[0].scenario_id == "recovery-shared"

    dumped = dump_recovery_policy(
        {
            "enabled": True,
            "rules": [{"scenario_id": "recovery-shared"}],
        }
    )
    assert dumped["rules"][0]["scope"] == {}
    assert dumped["rules"][0]["outcome"] == "retry_step"


def test_recovery_policy_preserves_timeout_ms():
    policy = validate_recovery_policy_shape(
        {
            "enabled": True,
            "rules": [
                {
                    "scenario_id": "recovery-shared",
                    "timeout_ms": 30_000,
                }
            ],
        }
    )

    assert policy.rules[0].timeout_ms == 30_000
    dumped = dump_recovery_policy(
        {
            "enabled": True,
            "rules": [{"scenario_id": "recovery-shared", "timeout_ms": 30_000}],
        }
    )
    assert dumped["rules"][0]["timeout_ms"] == 30_000


def test_run_scenario_passes_recovery_policy_to_child_scenario(monkeypatch):
    recovery_policy = {
        "enabled": True,
        "rules": [{"scenario_id": "recovery-shared", "timeout_ms": 30_000}],
    }
    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": recovery_policy,
            "_scenario_registry": {
                "by_id": {
                    "main-1": {
                        "steps": [{"type": "content_comment"}],
                        "variables": {},
                    }
                }
            },
        },
        call_stack=set(),
        serial="SN1",
    )
    result = {"ok": True}

    handle_run_scenario(sc, {"type": "run_scenario", "scenario_id": "main-1"}, 0, result)

    assert result["ok"] is True
    assert calls[0]["extra_scenario_keys"]["recovery_policy"] == recovery_policy


def test_detect_incident_app_popup_from_hierarchy():
    incident = detect_incident(
        device=object(),
        step={"platform": "example"},
        step_result={"ok": False, "message": "tap failed"},
        snapshot=ScreenSnapshot(
            xml='<node text="Turn on notifications for Example app" />'
        ),
    )

    assert incident is not None
    assert incident.type == "app_popup"
    assert incident.confidence >= 0.8


def test_detect_incident_profile_detour_for_comment_strategy():
    incident = detect_incident(
        device=object(),
        step={"strategy": "comments"},
        step_result={"ok": False, "message": "comment failed"},
        snapshot=ScreenSnapshot(
            xml='<node text="Add friend" /><node text="Followers" />'
        ),
    )

    assert incident is not None
    assert incident.type == "profile_page"


def test_parse_recovery_policy_disabled_empty():
    assert parse_recovery_policy({}).enabled is False
    assert parse_recovery_policy(None).rules == ()


def test_recovery_playbook_runs_without_default_text_match(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr(
        "tasks.scenario.executor.run_nested_scenario",
        run_nested,
    )

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "incident_type": "example_popup",
                        "scope": {"step_type_any": ["content_comment"]},
                        "scenario_id": "recovery-1",
                        "outcome": "retry_step",
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-1": {
                        "steps": [
                            {"type": "assert_element", "selector": "custom_popup"},
                            {"type": "tap_selector", "selector": "dismiss"},
                            {"type": "assert_element", "selector": "comment_box"},
                        ],
                        "variables": {},
                    }
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
    )

    decision = maybe_recover_step(
        sc,
        {"type": "content_comment"},
        0,
        {"ok": False, "message": "original step failed"},
    )

    assert decision.handled is True
    assert decision.retry_step is True
    assert calls[0]["steps"][0]["type"] == "assert_element"
    assert calls[0]["extra_scenario_keys"]["_recovery_disabled"] is True
    detected = decision.events[0]["payload"]
    assert detected["reason_code"] == "recovery_playbook"
    assert detected["evidence"]["source"] == "recovery_playbook"


@pytest.mark.parametrize(
    "step",
    [
        {"type": "content_comment", "strategy": "content_comments"},
        {"type": "open_post_detail"},
        {"type": "adb_shell"},
    ],
)
def test_shared_recovery_playbook_runs_for_any_failed_step(monkeypatch, step):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "scope": {},
                        "scenario_id": "recovery-shared",
                        "outcome": "retry_step",
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-shared": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
    )

    decision = maybe_recover_step(
        sc,
        step,
        0,
        {"ok": False, "message": "original step failed"},
    )

    assert decision.handled is True
    assert decision.retry_step is True
    assert calls[0]["steps"][0]["type"] == "tap_selector"
    assert decision.events[0]["payload"]["evidence"]["scope"] == {}


def test_shared_recovery_playbook_respects_rule_attempt_budget(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "scope": {},
                        "scenario_id": "recovery-shared",
                        "outcome": "retry_step",
                        "max_attempts": 1,
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-shared": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
    )

    first = maybe_recover_step(
        sc,
        {"type": "content_comment"},
        0,
        {"ok": False, "_recovery_incident_key": "same-incident"},
    )
    second = maybe_recover_step(
        sc,
        {"type": "open_post_detail"},
        0,
        {"ok": False, "_recovery_incident_key": "same-incident"},
    )

    assert first.handled is True
    assert second.handled is False
    assert len(calls) == 1


def test_recovery_budget_allows_same_step_rule_on_new_incidents(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "scope": {},
                        "scenario_id": "recovery-shared",
                        "outcome": "retry_step",
                        "max_attempts": 1,
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-shared": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
        trace_id="trace-1",
        call_stack=set(),
    )

    results = [
        maybe_recover_step(sc, {"type": "content_comment"}, 0, {"ok": False})
        for _ in range(3)
    ]

    assert [result.handled for result in results] == [True, True, True]
    assert len(calls) == 3
    state = sc.ctx["_recovery_state"]
    assert state["total_attempts"] == 3
    assert len(state["by_incident"]) == 3


def test_recovery_budget_blocks_same_incident_step_after_step_cap(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "max_attempts_per_step": 1,
                "rules": [
                    {
                        "scope": {},
                        "scenario_id": "recovery-shared",
                        "outcome": "retry_step",
                        "max_attempts": 3,
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-shared": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
    )

    first = maybe_recover_step(
        sc,
        {"type": "content_comment"},
        0,
        {"ok": False, "_recovery_incident_key": "same-incident"},
    )
    second = maybe_recover_step(
        sc,
        {"type": "content_comment"},
        0,
        {"ok": False, "_recovery_incident_key": "same-incident"},
    )

    assert first.handled is True
    assert second.handled is False
    assert len(calls) == 1


def test_recovery_budget_global_total_cap_blocks_across_incidents(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "max_total_attempts": 2,
                "rules": [
                    {
                        "scope": {},
                        "scenario_id": "recovery-shared",
                        "outcome": "retry_step",
                        "max_attempts": 1,
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-shared": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
    )

    results = [
        maybe_recover_step(sc, {"type": "content_comment"}, 0, {"ok": False})
        for _ in range(3)
    ]

    assert [result.handled for result in results] == [True, True, False]
    assert len(calls) == 2


def test_legacy_recovery_counters_are_not_budget_blockers(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "scope": {},
                        "scenario_id": "recovery-shared",
                        "outcome": "retry_step",
                        "max_attempts": 1,
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-shared": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                }
            },
        },
        ctx={
            "_recovery_state": {
                "total_attempts": 0,
                "by_step": {"0": 999},
                "by_rule": {"rule-1": 999},
            }
        },
        device=Device(),
        serial="SN1",
    )

    decision = maybe_recover_step(sc, {"type": "content_comment"}, 0, {"ok": False})

    assert decision.handled is True
    assert len(calls) == 1


def test_recovery_state_records_incident_key_in_state_and_events(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    def run_nested(sc, steps, **kwargs):
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "id": "shared",
                        "scope": {},
                        "scenario_id": "recovery-shared",
                        "outcome": "retry_step",
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-shared": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
        trace_id="trace-1",
        call_stack=set(),
    )

    step_result = {"ok": False}
    decision = maybe_recover_step(sc, {"type": "content_comment"}, 2, step_result)
    incident_key = step_result["_recovery_incident_key"]

    assert decision.handled is True
    assert sc.ctx["_recovery_state"]["by_incident"][incident_key] == 1
    assert sc.ctx["_recovery_state"]["by_incident_step"][f"{incident_key}:2"] == 1
    assert sc.ctx["_recovery_state"]["by_incident_rule"][f"{incident_key}:shared"] == 1
    assert sc.ctx["_recovery_state"]["last_incident"]["key"] == incident_key
    assert decision.events[0]["payload"]["incident_key"] == incident_key


def test_parse_recovery_policy_defaults_and_clamps_for_loop_recovery():
    defaulted = parse_recovery_policy({"enabled": True})
    clamped = parse_recovery_policy(
        {
            "enabled": True,
            "max_total_attempts": 999_999,
            "max_attempts_per_step": 999,
        }
    )

    assert defaulted.max_total_attempts == 100
    assert defaulted.max_attempts_per_step == 2
    assert defaulted.max_step_recovery_ms == 30_000
    assert clamped.max_total_attempts == 10_000
    assert clamped.max_attempts_per_step == 20
    assert parse_recovery_policy(
        {"enabled": True, "max_step_recovery_ms": 5_000_000}
    ).max_step_recovery_ms == 600_000


def test_recovery_playbooks_stop_at_the_step_time_ceiling(monkeypatch):
    """Attempt counters bound how many playbooks run, not how long.

    Each playbook is a full nested scenario; three of them that each wait out
    an 8s selector timeout is how a failed step reached 103s.
    """
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []
    clock = {"now": 1000.0}
    monkeypatch.setattr(
        recovery_runner, "time", SimpleNamespace(monotonic=lambda: clock["now"])
    )

    def run_nested(sc, steps, **kwargs):
        calls.append(kwargs.get("call_stack_add"))
        clock["now"] += 20.0  # this playbook burned 20 seconds and failed
        return {"success": False, "steps_executed": 1, "failed_message": "no luck"}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "max_step_recovery_ms": 30_000,
                "max_attempts_per_step": 10,  # counters must not be what stops us
                "rules": [
                    {"scope": {}, "scenario_id": f"recovery-{n}", "outcome": "retry_step"}
                    for n in (1, 2, 3)
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    f"recovery-{n}": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                    for n in (1, 2, 3)
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
    )

    decision = maybe_recover_step(sc, {"type": "content_comment"}, 0, {"ok": False})

    # Two playbooks fit inside 30s; the third never starts.
    assert calls == ["recovery-1", "recovery-2"]
    assert clock["now"] - 1000.0 == 40.0
    assert decision.handled is True
    assert decision.fail_message is not None


def test_recovery_time_ceiling_can_be_disabled(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []
    clock = {"now": 1000.0}
    monkeypatch.setattr(
        recovery_runner, "time", SimpleNamespace(monotonic=lambda: clock["now"])
    )

    def run_nested(sc, steps, **kwargs):
        calls.append(kwargs.get("call_stack_add"))
        clock["now"] += 20.0
        return {"success": False, "steps_executed": 1, "failed_message": "no luck"}

    monkeypatch.setattr("tasks.scenario.executor.run_nested_scenario", run_nested)

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "max_step_recovery_ms": 0,
                "max_attempts_per_step": 10,
                "rules": [
                    {"scope": {}, "scenario_id": f"recovery-{n}", "outcome": "retry_step"}
                    for n in (1, 2, 3)
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    f"recovery-{n}": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                    for n in (1, 2, 3)
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
    )

    maybe_recover_step(sc, {"type": "content_comment"}, 0, {"ok": False})

    assert calls == ["recovery-1", "recovery-2", "recovery-3"]


def test_recovery_playbook_skips_when_step_scope_does_not_match(monkeypatch):
    class Device:
        current_package = "com.example.app"
        current_activity = "MainActivity"

        def hierarchy_xml(self, force_refresh=False):
            return '<node text="Unexpected custom screen outside default list" />'

    calls = []

    def run_nested(sc, steps, **kwargs):
        calls.append({"steps": steps, **kwargs})
        return {"success": True, "steps_executed": len(steps)}

    monkeypatch.setattr(
        "tasks.scenario.executor.run_nested_scenario",
        run_nested,
    )

    sc = SimpleNamespace(
        scenario={
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "scope": {"step_type_any": ["content_comment"]},
                        "scenario_id": "recovery-1",
                        "outcome": "retry_step",
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-1": {
                        "steps": [{"type": "tap_selector", "selector": "dismiss"}],
                        "variables": {},
                    }
                }
            },
        },
        ctx={},
        device=Device(),
        serial="SN1",
    )

    decision = maybe_recover_step(
        sc,
        {"type": "open_post_detail"},
        0,
        {"ok": False, "message": "original step failed"},
    )

    assert decision.handled is False
    assert calls == []
