from tasks.scenario.steps import extraction as extraction_mod
from db.seeds.scenario_templates import BUILTIN_TEMPLATE_BY_NAME


class _FakeDevice:
    def __init__(self):
        self.calls = []

    def request_extra_data_xml(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
                "items": [{"display_name": "OpenClaw VN"}],
            },
        }


class _NoGroupDevice(_FakeDevice):
    def request_extra_data_xml(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "ingest": {
                "parsed_count": 0,
                "inserted_count": 0,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "no_groups"},
                "items": [],
            },
        }


def test_fb_groups_persists_without_content_collection_and_keeps_query(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setattr(
        extraction_mod,
        "_relay_extra_data_available",
        lambda _device: True,
    )
    device = _FakeDevice()
    ctx = {}
    scenario = {
        "_execution_id": "execution-a",
        "_campaign_id": "campaign-a",
        "_campaign_vars": {"__USER_ID__": "user-a"},
        "name": "group discovery",
    }
    result = {}

    handled = extraction_mod.request_edge_extra_data(
        device=device,
        serial="device-a",
        ctx=ctx,
        scenario=scenario,
        step={
            "edge_extra_data": True,
            "search_query": "${SEARCH_QUERY}",
        },
        strategy="fb_groups",
        result=result,
    )

    assert handled is True
    assert device.calls[0]["strategy"] == "fb_groups"
    assert device.calls[0]["context"]["persist"] is True
    assert device.calls[0]["context"]["return_items"] is True
    assert device.calls[0]["context"]["search_query"] == "${SEARCH_QUERY}"
    assert ctx["groups"] == [{"display_name": "OpenClaw VN"}]


def test_fb_groups_delegates_bounded_crawl_to_agent_and_breaks_legacy_loop(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setattr(
        extraction_mod,
        "_relay_extra_data_available",
        lambda _device: True,
    )
    device = _FakeDevice()
    ctx = {"_loop_iter": 0}
    result = {}

    handled = extraction_mod.request_edge_extra_data(
        device=device,
        serial="device-a",
        ctx=ctx,
        scenario={
            "_execution_id": "execution-a",
            "_campaign_vars": {
                "__USER_ID__": "user-a",
                "MAX_PAGES": 12,
            },
        },
        step={
            "edge_extra_data": True,
            "search_query": "openclaw",
            "stop_if_no_new": False,
            "no_new_threshold": 2,
            "entity_scroll_pause_s": 0.25,
        },
        strategy="fb_groups",
        result=result,
    )

    assert handled is True
    context = device.calls[0]["context"]
    assert context["max_pages"] == 12
    assert context["max_items"] == 500
    assert context["stop_if_no_new"] is False
    assert context["no_new_threshold"] == 2
    assert context["entity_scroll_pause_s"] == 0.25
    assert ctx["_break"] is True


def test_fb_groups_does_not_break_unrelated_outer_loop(monkeypatch) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setattr(
        extraction_mod,
        "_relay_extra_data_available",
        lambda _device: True,
    )
    ctx = {"_loop_iter": 0}

    handled = extraction_mod.request_edge_extra_data(
        device=_FakeDevice(),
        serial="device-a",
        ctx=ctx,
        scenario={"_execution_id": "execution-a"},
        step={
            "edge_extra_data": True,
            "search_query": "openclaw",
            "max_pages": 5,
        },
        strategy="fb_groups",
        result={},
    )

    assert handled is True
    assert "_break" not in ctx


def test_fb_groups_fails_the_step_when_visible_results_parse_to_zero(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setattr(
        extraction_mod,
        "_relay_extra_data_available",
        lambda _device: True,
    )
    device = _NoGroupDevice()
    ctx = {"_loop_iter": 0}
    result = {}

    handled = extraction_mod.request_edge_extra_data(
        device=device,
        serial="device-a",
        ctx=ctx,
        scenario={"_execution_id": "execution-a"},
        step={"edge_extra_data": True, "search_query": "openclaw"},
        strategy="fb_groups",
        result=result,
    )

    assert handled is True
    assert result["ok"] is False
    assert result["reason_code"] == "no_groups"
    assert "không đọc được group" in result["message"]
    assert "_break" not in ctx


def test_group_discovery_template_uses_one_agent_owned_crawl_step() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Khám phá nguồn từ Facebook Groups"]
    group_steps = [
        step
        for step in template["steps"]
        if step.get("strategy") == "fb_groups"
    ]

    assert len(group_steps) == 1
    assert not any(step.get("type") == "loop" for step in template["steps"])
    assert group_steps[0] == {
        "type": "extract",
        "strategy": "fb_groups",
        "edge_extra_data": True,
        "search_query": "${SEARCH_QUERY}",
        "max_pages": "${MAX_PAGES}",
        "max_items": 500,
        "stop_if_no_new": True,
        "no_new_threshold": 2,
        "entity_scroll_pause_s": 0.6,
        "edge_extra_timeout_s": 180,
    }
