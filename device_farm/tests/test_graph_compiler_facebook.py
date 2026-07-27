from __future__ import annotations

from common.graph_compiler import compile_graph_to_steps, steps_to_graph
from db.seeds.scenario_templates import BUILTIN_TEMPLATE_BY_NAME


def _count_fb_comment_extracts(steps: list[dict]) -> int:
    total = 0
    for step in steps:
        if step.get("type") == "extract" and step.get("strategy") == "fb_comments":
            total += 1
        for key in ("steps", "then", "else"):
            children = step.get(key)
            if isinstance(children, list):
                total += _count_fb_comment_extracts(children)
        branches = step.get("branches")
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict) and isinstance(branch.get("steps"), list):
                    total += _count_fb_comment_extracts(branch["steps"])
    return total


def test_facebook_comment_button_graph_round_trip_keeps_then_branch() -> None:
    steps = [
        {
            "type": "fb_tap_comment_button",
            "then": [
                {
                    "type": "extract",
                    "strategy": "fb_comments",
                    "edge_extra_data": True,
                }
            ],
            "else": [{"type": "wait", "seconds": 1}],
        }
    ]

    nodes, edges = steps_to_graph(steps)
    assert any(
        node.get("type") == "extract"
        and node.get("config", {}).get("strategy") == "fb_comments"
        and node.get("scope", {}).get("branch") == "then"
        for node in nodes
    )

    round_tripped = compile_graph_to_steps(nodes, edges)
    assert _count_fb_comment_extracts(round_tripped) == 1


def test_facebook_group_template_keeps_extra_data_tuning_in_steps_not_variables() -> None:
    spec = BUILTIN_TEMPLATE_BY_NAME["Crawl bài viết + bình luận 1 nhóm Facebook"]
    variables = set(spec["variables"])
    extra_data_keys = {
        "MAX_COMMENT_SCROLLS",
        "MAX_COMMENTS_PER_POST",
        "MIN_COMMENT_SCAN_PASSES",
        "COMMENT_NO_NEW_THRESHOLD",
        "EXTRACT_PROFILE",
        "FB_POSTS_STRATEGY_VERSION",
        "FB_COMMENTS_STRATEGY_VERSION",
    }

    assert variables.isdisjoint(extra_data_keys)
    assert not _contains_step_type(spec["steps"], "tap_fb_comment_button")
    assert not _contains_step_type(spec["steps"], "fb_tap_comment_button")
    assert _contains_step_type(spec["steps"], "fb_find_comment_button")
    assert _contains_step_type(spec["steps"], "fb_tap_comment_target")
    assert _contains_step_type(spec["steps"], "fb_apply_comment_filter")

    nodes, edges = steps_to_graph(spec["steps"])
    round_tripped = compile_graph_to_steps(nodes, edges)
    assert _count_fb_comment_extracts(spec["steps"]) == 1
    assert _count_fb_comment_extracts(round_tripped) == 1


def test_facebook_group_templates_open_catalog_target_with_stable_selector() -> None:
    def has_step(steps: list[dict], predicate) -> bool:
        for step in steps:
            if predicate(step):
                return True
            for key in ("steps", "then", "else"):
                children = step.get(key)
                if isinstance(children, list) and has_step(children, predicate):
                    return True
        return False

    for name in (
        "Crawl bài viết + bình luận 1 nhóm Facebook",
        "fb_group_1h",
        "craw fb",
    ):
        spec = BUILTIN_TEMPLATE_BY_NAME[name]
        assert has_step(
            spec["steps"],
            lambda step: (
                step.get("type") == "tap_selector"
                and step.get("by") == "${TARGET_SELECTOR_BY}"
                and step.get("value") == "${TARGET_SELECTOR_VALUE}"
            ),
        ), name
        assert has_step(
            spec["steps"],
            lambda step: (
                step.get("type") == "tap_selector"
                and step.get("by") == "${TARGET_FALLBACK_SELECTOR_BY}"
                and step.get("value") == "${TARGET_FALLBACK_SELECTOR_VALUE}"
            ),
        ), name

    assert has_step(
        BUILTIN_TEMPLATE_BY_NAME["craw fb"]["steps"],
        lambda step: (
            step.get("type") == "tap_selector"
            and step.get("by") == "descriptionContains"
            and step.get("value") == "tab Nhóm"
        ),
    )


def test_facebook_builtin_post_comment_flows_stay_on_detail_until_comments_extracted() -> None:
    flows: list[tuple[str, list[dict], int, int, int, int, int]] = []
    for spec in BUILTIN_TEMPLATE_BY_NAME.values():
        if spec.get("category") != "facebook":
            continue
        flows.extend(
            (spec["name"], sibling_steps, post_index, find_index, tap_index, filter_index, comment_index)
            for sibling_steps, post_index, find_index, tap_index, filter_index, comment_index in _post_comment_sibling_flows(spec["steps"])
        )

    assert flows
    for name, sibling_steps, post_index, find_index, tap_index, filter_index, comment_index in flows:
        assert post_index < find_index < tap_index < filter_index < comment_index, name
        assert not any(_is_back_step(step) for step in sibling_steps[post_index + 1 : comment_index]), name

        comment_step = sibling_steps[comment_index]
        assert comment_step.get("require_verified_parent") is True, name
        return_steps = sibling_steps[comment_index + 1 :]
        assert return_steps and _is_back_step(return_steps[0]), name
        assert any(
            step.get("type") == "if_element"
            and step.get("by") == "text"
            and step.get("value") == "Bài viết"
            for step in return_steps
        ), name


def _contains_step_type(steps: list[dict], step_type: str) -> bool:
    for step in steps:
        if step.get("type") == step_type:
            return True
        for key in ("steps", "then", "else"):
            children = step.get(key)
            if isinstance(children, list) and _contains_step_type(children, step_type):
                return True
        branches = step.get("branches")
        if isinstance(branches, list):
            for branch in branches:
                if (
                    isinstance(branch, dict)
                    and isinstance(branch.get("steps"), list)
                    and _contains_step_type(branch["steps"], step_type)
                ):
                    return True
    return False


def _post_comment_sibling_flows(steps: list[dict]) -> list[tuple[list[dict], int, int, int, int, int]]:
    flows: list[tuple[list[dict], int, int, int, int, int]] = []
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
        for key in ("steps", "then", "else"):
            children = step.get(key)
            if isinstance(children, list):
                flows.extend(_post_comment_sibling_flows(children))
        branches = step.get("branches")
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict) and isinstance(branch.get("steps"), list):
                    flows.extend(_post_comment_sibling_flows(branch["steps"]))
    return flows


def _first_step_index(steps: list[dict], predicate) -> int | None:
    for index, step in enumerate(steps):
        if predicate(step):
            return index
    return None


def _is_fb_post_extract(step: dict) -> bool:
    return step.get("type") == "extract" and step.get("strategy") == "fb_posts"


def _is_fb_comment_extract(step: dict) -> bool:
    return step.get("type") == "extract" and step.get("strategy") == "fb_comments"


def _is_back_step(step: dict) -> bool:
    return step.get("type") == "key" and step.get("key") == "back"
