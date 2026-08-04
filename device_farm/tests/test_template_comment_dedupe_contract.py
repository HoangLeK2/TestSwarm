from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db.seeds.scenario_templates import (
    BUILTIN_TEMPLATE_BY_NAME,
    _graph_mirror_from_steps,
)


ROOT = Path(__file__).resolve().parent.parent


def _walk_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in steps or []:
        out.append(step)
        if step.get("type") == "loop":
            out.extend(_walk_steps(step.get("steps")))
        for key in ("then", "else"):
            out.extend(_walk_steps(step.get(key)))
        for branch in step.get("branches") or []:
            if isinstance(branch, dict):
                out.extend(_walk_steps(branch.get("steps")))
    return out


def _assert_comment_extract_dedupe_comment_key(steps: list[dict[str, Any]]) -> None:
    comment_extracts = [
        s for s in _walk_steps(steps)
        if s.get("type") == "extract" and s.get("strategy") == "fb_comments"
    ]
    assert comment_extracts, "expected at least one fb_comments extract step"
    for step in comment_extracts:
        assert step.get("dedupe_field") == "comment_key", step
        assert step.get("require_verified_parent") is True, step


def _assert_comment_flow_stays_on_detail_until_comments(steps: list[dict[str, Any]]) -> None:
    sibling_flows = _post_comment_sibling_flows(steps)
    assert sibling_flows, "expected at least one fb_posts -> split comment node sibling flow"
    for flow_steps, post_index, find_index, tap_index, filter_index, comment_index in sibling_flows:
        assert post_index < find_index < tap_index < filter_index < comment_index

        intervening_steps = flow_steps[post_index + 1 : comment_index]
        assert not any(_is_back_step(step) for step in intervening_steps)

        comment_step = flow_steps[comment_index]
        assert comment_step.get("require_verified_parent") is True, comment_step
        return_steps = flow_steps[comment_index + 1 :]
        assert return_steps and _is_back_step(return_steps[0]), comment_step
        assert any(
            step.get("type") == "if_element"
            and step.get("by") == "text"
            and step.get("value") == "Bài viết"
            for step in return_steps
        ), comment_step


def test_index_json_comment_extract_uses_comment_key_dedupe() -> None:
    data = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    _assert_comment_extract_dedupe_comment_key(data.get("steps", []))
    _assert_comment_flow_stays_on_detail_until_comments(data.get("steps", []))


def test_scenario_fb_group_crawl_comment_extract_uses_comment_key_dedupe() -> None:
    data = json.loads((ROOT / "scenarios" / "fb_group_crawl.json").read_text(encoding="utf-8"))
    _assert_comment_extract_dedupe_comment_key(data.get("steps", []))
    _assert_comment_flow_stays_on_detail_until_comments(data.get("steps", []))


def test_facebook_nurture_template_branches_by_target_object() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Chiến lược nuôi Facebook theo đối tượng"]
    assert template["variables"]["TARGET_OBJECT_TYPE"] == "fanpage"

    steps = template["steps"]
    flat_steps = _walk_steps(steps)

    assert any(
        step.get("type") == "if_variable"
        and step.get("name") == "TARGET_OBJECT_TYPE"
        and step.get("equals") == "fanpage"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "if_variable"
        and step.get("name") == "TARGET_OBJECT_TYPE"
        and step.get("equals") == "post"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_selector"
        and step.get("value") == "${FANPAGE_ROW_TEXT}"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_selector"
        and step.get("value") == "${POST_ROW_TEXT}"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_selector"
        and step.get("value") == "${PEOPLE_ROW_TEXT}"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "content_interaction"
        and step.get("action") == "like"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "connection_request"
        and step.get("action") == "request"
        for step in flat_steps
    )

    nodes, edges = _graph_mirror_from_steps(steps)
    assert nodes
    assert edges


def _post_comment_sibling_flows(
    steps: list[dict[str, Any]],
) -> list[tuple[list[dict[str, Any]], int, int, int, int, int]]:
    flows: list[tuple[list[dict[str, Any]], int, int, int, int, int]] = []
    post_index = _first_step_index(steps, _is_fb_post_extract)
    find_index = _first_step_index(steps, lambda step: step.get("type") == "fb_find_comment_button")
    tap_index = _first_step_index(steps, lambda step: step.get("type") == "fb_tap_comment_target")
    filter_index = _first_step_index(steps, lambda step: step.get("type") == "fb_apply_comment_filter")
    comment_index = _first_step_index(steps, _is_fb_comment_extract)
    if (
        post_index is not None
        and find_index is not None
        and tap_index is not None
        and filter_index is not None
        and comment_index is not None
    ):
        flows.append((steps, post_index, find_index, tap_index, filter_index, comment_index))

    for step in steps:
        if step.get("type") == "loop":
            flows.extend(_post_comment_sibling_flows(step.get("steps") or []))
        for key in ("then", "else"):
            children = step.get(key)
            if isinstance(children, list):
                flows.extend(_post_comment_sibling_flows(children))
    return flows


def _first_step_index(steps: list[dict[str, Any]], predicate) -> int | None:
    for index, step in enumerate(steps):
        if predicate(step):
            return index
    return None


def _is_fb_post_extract(step: dict[str, Any]) -> bool:
    return step.get("type") == "extract" and step.get("strategy") == "fb_posts"


def _is_fb_comment_extract(step: dict[str, Any]) -> bool:
    return step.get("type") == "extract" and step.get("strategy") == "fb_comments"


def _is_back_step(step: dict[str, Any]) -> bool:
    return step.get("type") == "key" and step.get("key") == "back"
