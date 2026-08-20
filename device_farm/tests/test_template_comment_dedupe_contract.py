from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from api.schemas.scenario import ScenarioModel
from db.models.enums import ScenarioKind
from db.seeds.scenario_templates import (
    BUILTIN_TEMPLATE_BY_NAME,
    _graph_mirror_from_steps,
)
from services.scenario_dsl.body_validator import validate_org_scenario_body

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
        if s.get("type") == "extract" and s.get("entity") == "comments"
    ]
    assert comment_extracts, "expected at least one fb_comments extract step"
    for step in comment_extracts:
        assert step.get("dedupe_field") == "comment_key", step
        assert step.get("require_verified_parent") is True, step


def _assert_comment_flow_stays_on_detail_until_comments(steps: list[dict[str, Any]]) -> None:
    sibling_flows = _post_comment_sibling_flows(steps)
    assert sibling_flows, "expected at least one posts -> split comment node sibling flow"
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
    ) is False
    assert any(
        step.get("type") == "social_select_target" and step.get("target_type") == "post"
        and step.get("display_text") == "${POST_ROW_TEXT}"
        and step.get("save_as") == "_post_target"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "social_select_target" and step.get("target_type") == "person"
        and step.get("display_name") == "${PEOPLE_ROW_TEXT}"
        and step.get("save_as") == "_people_target"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "content_interaction"
        and step.get("action") == "like"
        and step.get("require_verified_target") == "_post_target"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "content_interaction"
        and step.get("action") == "like"
        and step.get("require_verified_target") == "_people_target"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "connection_request"
        and step.get("action") == "request"
        and step.get("require_verified_target") == "_people_target"
        for step in flat_steps
    )

    nodes, edges = _graph_mirror_from_steps(steps)
    assert nodes
    assert edges


def test_facebook_nurture_template_passes_sequence_body_validator() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Chiến lược nuôi Facebook theo đối tượng"]

    async def _validate():
        return await validate_org_scenario_body(
            None,
            org_id="org",
            scenario_id="scenario",
            kind=ScenarioKind.SEQUENCE.value,
            body={
                "steps": template["steps"],
                "variables": template["variables"],
            },
        )

    result = asyncio.run(_validate())

    assert result.status == "valid"
    assert result.errors == []


@pytest.mark.parametrize(
    "template_name",
    [
        "Crawl bài viết + bình luận Fanpage Facebook",
        "Nuôi Facebook - Tương tác Fanpage",
    ],
)
def test_fanpage_templates_use_assigned_page_without_relogin(template_name: str) -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[template_name]
    flat_steps = _walk_steps(template["steps"])

    assert template["variables"]["PAGE_SEARCH"] == "ten fanpage"
    assert template["steps"][3]["type"] == "platform_session_gate"
    assert template["steps"][3]["phase"] == "preflight"
    assert not any(step.get("type") == "login_if_needed" for step in flat_steps)
    assert any(
        step.get("type") == "if_variable"
        and step.get("name") == "PLATFORM_SESSION_READY"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "if_variable"
        and step.get("name") == "TARGET_SELECTOR_VALUE"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_ratio"
        and step.get("x") == 0.5
        and step.get("y") == 0.22
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_selector"
        and step.get("value") == "${PAGE_ROW_TEXT}"
        for step in flat_steps
    )
    tab_selectors = [
        step
        for step in flat_steps
        if step.get("type") == "tap_selector"
        and step.get("value") in {"tab Trang", "Trang", "Pages"}
    ]
    assert tab_selectors
    assert all(step.get("ignore_error") is True for step in tab_selectors)


def test_fanpage_crawl_template_collects_posts_and_comments() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Crawl bài viết + bình luận Fanpage Facebook"]
    flat_steps = _walk_steps(template["steps"])
    post_extract = next(
        step
        for step in flat_steps
        if step.get("type") == "extract" and step.get("entity") == "posts"
    )
    comment_extract = next(
        step
        for step in flat_steps
        if step.get("type") == "extract" and step.get("entity") == "comments"
    )

    assert post_extract["collection"] == "${SAVE_COLLECTION}"
    assert post_extract["content_type"] == "fb_post"
    assert post_extract["tags"] == "page,crawl,${PAGE_CONTEXT}"
    assert comment_extract["collection"] == "${SAVE_COLLECTION}"
    assert comment_extract["content_type"] == "fb_comment"
    assert comment_extract["dedupe_field"] == "comment_key"
    assert comment_extract["require_verified_parent"] is True
    assert comment_extract["tags"] == "page,comment,${PAGE_CONTEXT}"


def test_fanpage_nurture_template_follows_and_touches_feed() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Nuôi Facebook - Tương tác Fanpage"]
    flat_steps = _walk_steps(template["steps"])
    session_gate = next(
        step
        for step in template["steps"]
        if step.get("id") == "fanpage_nurture_requires_ready_session"
    )
    page_loop = next(step for step in session_gate["then"] if step.get("type") == "loop")
    page_steps = page_loop["steps"]

    assert template["variables"]["FOLLOW_PAGE"] == "true"
    assert template["variables"]["PAGE_TARGETS"] == ["ten fanpage"]
    assert template["variables"]["PAGE_ROW_TEXTS"] == ["Tên Fanpage"]
    assert template["variables"]["PAGE_COUNT"] == 1
    assert template["variables"]["MAX_TOUCHES"] == 20
    assert page_loop.get("count") == "${PAGE_COUNT}"
    assert page_loop.get("loop_var") == "PAGE_INDEX"
    assert page_steps[0] == {
        "type": "set_variable",
        "name": "PAGE_SEARCH_CURRENT",
        "from_list": "${PAGE_TARGETS}",
        "from_list_index": "${PAGE_INDEX}",
    }
    assert page_steps[1] == {
        "type": "set_variable",
        "name": "PAGE_ROW_TEXT_CURRENT",
        "from_list": "${PAGE_ROW_TEXTS}",
        "from_list_index": "${PAGE_INDEX}",
    }
    assert page_steps[2] == {
        "type": "set_variable",
        "name": "PAGE_CONTEXT",
        "value": "${PAGE_ROW_TEXT_CURRENT}",
    }
    assert page_steps[3].get("type") == "tap_selector"
    assert page_steps[3].get("by") == "content-desc"
    assert page_steps[3].get("value") == "Tìm kiếm"
    assert page_steps[5].get("type") == "input_text"
    assert page_steps[5].get("text") == "${PAGE_SEARCH_CURRENT}"
    assert page_steps[5].get("clear_first") is True
    assert page_steps[7] == {"type": "key", "key": "enter"}
    page_row_tap = page_steps[9]
    assert page_row_tap.get("type") == "tap_xml_match"
    assert page_row_tap.get("attr") == "content-desc"
    assert page_row_tap.get("contains") == "${PAGE_ROW_TEXT_CURRENT}"
    assert page_row_tap.get("clickable") is True
    assert page_row_tap.get("timeout") == 10
    assert page_steps[11].get("type") == "if_variable"
    assert page_steps[11].get("name") == "FOLLOW_PAGE"
    assert not any(
        step.get("type") == "tap_ratio"
        and step.get("x") == 0.5
        and step.get("y") == 0.22
        for step in flat_steps
    )
    assert not any(
        step.get("type") == "tap_selector"
        and step.get("value") in {"Trang", "Pages"}
        for step in page_steps
    )
    assert not any(
        step.get("type") == "if_variable"
        and step.get("name") == "PAGE_COUNT"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "if_variable"
        and step.get("name") == "FOLLOW_PAGE"
        and step.get("equals") == "true"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "if_element"
        and step.get("by") == "content-desc"
        and step.get("value") == "Theo dõi"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_selector"
        and step.get("by") == "content-desc"
        and step.get("value") == "Follow"
        for step in flat_steps
    )
    assert not any(
        step.get("type") == "tap_selector"
        and step.get("value") in {"Bài viết", "Posts"}
        for step in page_steps
    )
    assert any(
        step.get("id") == "back_to_page_search_before_next_page"
        and step.get("type") == "key"
        and step.get("key") == "back"
        for step in page_steps
    )
    assert any(
        step.get("type") == "content_interaction"
        and step.get("platform") == "facebook"
        and step.get("action") == "like"
        and step.get("id") == "fanpage_page_${PAGE_INDEX}_nurture_like_${_TOUCH_INDEX}"
        and step.get("ignore_error") is True
        and step.get("post_capture") is True
        and "require_capture" not in step
        for step in flat_steps
    )
    assert any(
        step.get("type") == "loop"
        and step.get("loop_var") == "_TOUCH_INDEX"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "set_variable"
        and step.get("name") == "_nurture_target"
        and step.get("value") == "fanpage:${PAGE_CONTEXT}"
        for step in flat_steps
    )


def test_fanpage_nurture_search_replaces_previous_query() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Nuôi Facebook - Tương tác Fanpage"]
    flat_steps = _walk_steps(template["steps"])
    search_inputs = [
        step
        for step in flat_steps
        if step.get("type") == "input_text"
        and step.get("text") in {"${PAGE_SEARCH_CURRENT}", "${PAGE_SEARCH}"}
    ]

    assert search_inputs
    assert all(step.get("clear_first") is True for step in search_inputs)


@pytest.mark.parametrize(
    "template_name",
    [
        "Crawl bài viết + bình luận Fanpage Facebook",
        "Nuôi Facebook - Tương tác Fanpage",
    ],
)
def test_fanpage_templates_pass_sequence_body_validator(template_name: str) -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[template_name]

    async def _validate():
        return await validate_org_scenario_body(
            None,
            org_id="org",
            scenario_id="scenario",
            kind=ScenarioKind.SEQUENCE.value,
            body={
                "steps": template["steps"],
                "variables": template["variables"],
            },
        )

    result = asyncio.run(_validate())

    assert result.status == "valid"
    assert result.errors == []


@pytest.mark.parametrize(
    "template_name",
    [
        "Nuôi Facebook - Tương tác bài viết trên Feed",
        "Nuôi Facebook - Tương tác bài viết trong Group",
        "Nuôi Facebook - Kết bạn theo ứng viên đã duyệt",
    ],
)
def test_candidate_nurture_templates_pass_both_validators(template_name: str) -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[template_name]
    payload = {"steps": template["steps"], "variables": template["variables"]}

    assert ScenarioModel.validate_dict(payload) == []

    async def _validate():
        return await validate_org_scenario_body(
            None,
            org_id="org",
            scenario_id="scenario",
            kind=ScenarioKind.SEQUENCE.value,
            body=payload,
        )

    result = asyncio.run(_validate())
    assert result.status == "valid"
    assert result.errors == []


def test_connection_template_uses_visible_common_context_scan() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[
        "Nuôi Facebook - Kết bạn theo ứng viên đã duyệt"
    ]
    flat_steps = _walk_steps(template["steps"])
    connector = next(
        step for step in flat_steps if step.get("type") == "social_connect_visible_people"
    )
    open_surface = next(
        step
        for step in flat_steps
        if step.get("id") == "candidate_profile_open_friends_surface"
    )

    assert open_surface["type"] == "if_element"
    assert connector["require_common"] is True
    assert connector["min_score"] == "${CONNECTION_MIN_COMMON_SCORE}"
    assert connector["common_keywords"] == "${CONNECTION_COMMON_KEYWORDS}"
    assert "group" not in connector["forbidden_keywords"]
    assert "nhóm" not in connector["forbidden_keywords"]
    assert all(step.get("type") != "lease_connection_candidate" for step in flat_steps)
    assert all(not (step.get("type") == "social_select_target" and step.get("target_type") == "person") for step in flat_steps)
    assert all(step.get("type") != "connection_request" for step in flat_steps)


def test_candidate_templates_process_configurable_unique_batches() -> None:
    post = BUILTIN_TEMPLATE_BY_NAME[
        "Nuôi Facebook - Tương tác bài viết trên Feed"
    ]
    group_post = BUILTIN_TEMPLATE_BY_NAME[
        "Nuôi Facebook - Tương tác bài viết trong Group"
    ]
    friend = BUILTIN_TEMPLATE_BY_NAME[
        "Nuôi Facebook - Kết bạn theo ứng viên đã duyệt"
    ]
    post_steps = _walk_steps(post["steps"])
    group_post_steps = _walk_steps(group_post["steps"])
    friend_steps = _walk_steps(friend["steps"])

    assert post["variables"]["POST_TARGET_COUNT"] == 5
    assert group_post["variables"]["POST_TARGET_COUNT"] == 5
    assert post["variables"]["POST_RUN_HOURS"] == 8
    assert group_post["variables"]["POST_RUN_HOURS"] == 8
    assert post["variables"]["POST_RUN_SECONDS"] == 28800
    assert group_post["variables"]["POST_RUN_SECONDS"] == 28800
    assert group_post["variables"]["GROUP_SCAN_SECONDS"] == 28800
    assert group_post["variables"]["GROUP_COUNT"] == 2
    assert group_post["variables"]["GROUP_SEARCHES"] == ["ten group 1", "ten group 2"]
    assert group_post["variables"]["GROUP_ROW_TEXTS"] == ["Tên group 1", "Tên group 2"]
    assert post["variables"]["POST_SCAN_CYCLES"] == 9999
    assert group_post["variables"]["POST_SCAN_CYCLES"] == 9999
    assert friend["variables"]["CONNECTION_TARGET_COUNT"] == 20
    assert any(
        step.get("type") == "social_connect_visible_people"
        and step.get("target_count") == "${CONNECTION_TARGET_COUNT}"
        for step in friend_steps
    )
    feed_scan = next(
        step for step in post_steps if step.get("type") == "social_scan_posts_interact"
    )
    group_scan = next(
        step
        for step in group_post_steps
        if step.get("type") == "social_scan_posts_interact"
    )
    feed_loop = next(
        step for step in post_steps if step.get("id") == "feed_post_scan_8h_loop"
    )
    group_loop = next(
        step for step in group_post_steps if step.get("id") == "group_post_scan_8h_loop"
    )
    multi_group_loop = next(
        step
        for step in group_post_steps
        if step.get("id") == "group_post_multi_group_loop"
    )
    assert feed_loop["type"] == "loop"
    assert feed_loop["count"] == "${POST_SCAN_CYCLES}"
    assert feed_loop["duration_seconds"] == "${POST_RUN_SECONDS}"
    assert multi_group_loop["type"] == "loop"
    assert multi_group_loop["count"] == "${GROUP_COUNT}"
    assert multi_group_loop["loop_var"] == "GROUP_INDEX"
    assert group_loop["type"] == "loop"
    assert group_loop["count"] == "${POST_SCAN_CYCLES}"
    assert group_loop["duration_seconds"] == "${GROUP_SCAN_SECONDS}"
    assert feed_scan["keywords"] == "${POST_KEYWORDS}"
    assert feed_scan["keywords_var"] == "POST_KEYWORDS"
    assert feed_scan["comment_text"] == "${COMMENT_TEXT}"
    assert feed_scan["target_count"] == "${POST_TARGET_COUNT}"
    assert feed_scan["max_scrolls"] == "${MAX_SCROLLS}"
    assert group_scan["keywords"] == "${POST_KEYWORDS}"
    assert group_scan["keywords_var"] == "POST_KEYWORDS"
    assert group_scan["comment_text"] == "${COMMENT_TEXT}"
    group_search_current = next(
        step
        for step in group_post_steps
        if step.get("type") == "set_variable"
        and step.get("name") == "GROUP_SEARCH_CURRENT"
    )
    group_row_current = next(
        step
        for step in group_post_steps
        if step.get("type") == "set_variable"
        and step.get("name") == "GROUP_ROW_TEXT_CURRENT"
    )
    back_to_search = next(
        step
        for step in group_post_steps
        if step.get("id") == "back_to_page_search_before_next_page"
    )
    assert group_search_current["from_list"] == "${GROUP_SEARCHES}"
    assert group_search_current["from_list_index"] == "${GROUP_INDEX}"
    assert group_row_current["from_list"] == "${GROUP_ROW_TEXTS}"
    assert group_row_current["from_list_index"] == "${GROUP_INDEX}"
    group_row_tap = next(
        step
        for step in group_post_steps
        if step.get("type") == "tap_xml_match"
        and step.get("contains") == "${GROUP_ROW_TEXT_CURRENT}"
    )
    assert group_row_tap["attr"] == "content-desc"
    assert group_row_tap["clickable"] is True
    assert group_post_steps.index(group_scan) > next(
        index
        for index, step in enumerate(group_post_steps)
        if step.get("type") == "tap_xml_match"
        and step.get("contains") == "${GROUP_ROW_TEXT_CURRENT}"
    )
    assert group_post_steps.index(back_to_search) > group_post_steps.index(group_scan)
    assert all(step.get("type") != "lease_source_target" for step in post_steps)
    assert all(not (step.get("type") == "social_select_target" and step.get("target_type") == "post") for step in post_steps)
    assert all(step.get("type") != "content_interaction" for step in post_steps)
    assert any(
        step.get("type") == "social_connect_visible_people"
        and step.get("require_common") is True
        for step in friend_steps
    )


def test_login_template_establishes_account_scoped_session_provenance() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Đăng nhập Facebook"]
    flat_steps = _walk_steps(template["steps"])
    gates = [step for step in flat_steps if step.get("type") == "platform_session_gate"]

    assert [gate["phase"] for gate in gates] == ["preflight", "confirm"]
    assert template["steps"][3]["type"] == "platform_session_gate"
    assert template["steps"][4]["type"] == "if_variable"


@pytest.mark.parametrize(
    "template_name",
    [
        "Nuôi Facebook - Tương tác bài viết trên Feed",
        "Nuôi Facebook - Tương tác bài viết trong Group",
        "Nuôi Facebook - Kết bạn theo ứng viên đã duyệt",
    ],
)
def test_candidate_nurture_templates_run_login_gate_first(template_name: str) -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[template_name]
    flat_steps = _walk_steps(template["steps"])
    gates = [step for step in flat_steps if step.get("type") == "platform_session_gate"]
    login_steps = [
        step for step in flat_steps if step.get("type") == "login_if_needed"
    ]
    first_work_index = next(
        index
        for index, step in enumerate(flat_steps)
        if step.get("type") in {
            "loop",
            "social_connect_visible_people",
            "social_scan_posts_interact",
        }
    )
    session_wrapper = template["steps"][4]

    assert template["steps"][0]["type"] == "launch_app"
    assert [gate["phase"] for gate in gates] == ["preflight"]
    assert login_steps == []
    assert all(step.get("type") != "run_scenario" for step in flat_steps)
    assert first_work_index > 3
    assert session_wrapper["type"] == "if_variable"
    assert session_wrapper["name"] == "PLATFORM_SESSION_READY"


def test_login_template_uses_facebook_credentials_only() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Đăng nhập Facebook"]
    flat_steps = _walk_steps(template["steps"])

    assert template["variables"] == {}
    assert "google" not in template["tags"]
    assert not any(
        "google" in str(value).lower()
        for step in flat_steps
        for value in step.values()
    )
    login_step = next(
        step for step in flat_steps if step.get("type") == "login_if_needed"
    )
    fields = login_step["profile"]["login_recipe"]["fields"]
    assert fields["username"]["value_from"] == "account.username"
    assert fields["password"]["value_from"] == "account.password"


def test_publish_post_template_posts_then_likes_and_comments_verified_post() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Đăng bài Facebook rồi like/comment"]
    flat_steps = _walk_steps(template["steps"])

    assert template["variables"]["POST_TEXT"] == ""
    assert template["variables"]["COMMENT_TEXT"]
    assert [step["phase"] for step in flat_steps if step.get("type") == "platform_session_gate"] == [
        "preflight",
        "confirm",
    ]
    assert any(step.get("type") == "login_if_needed" for step in flat_steps)
    assert any(
        step.get("type") == "if_element"
        and step.get("by") == "text"
        and step.get("value") == "${POST_COMPOSER_LABEL}"
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_ratio"
        and step.get("x") == 0.5
        and step.get("y") == 0.225
        for step in flat_steps
    )
    assert any(
        step.get("id") == "publish_post_focus_textarea"
        and step.get("type") == "tap_ratio"
        and step.get("x") == 0.45
        and step.get("y") == 0.34
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_ratio"
        and step.get("x") == 0.85
        and step.get("y") == 0.955
        for step in flat_steps
    )
    assert any(
        step.get("type") == "tap_ratio"
        and step.get("x") == 0.5
        and step.get("y") == 0.955
        for step in flat_steps
    )
    assert any(
        step.get("type") == "input_text"
        and step.get("text") == "${POST_TEXT}"
        for step in flat_steps
    )

    target = next(
        step for step in flat_steps if step.get("id") == "publish_post_select_created_post"
    )
    assert target["type"] == "social_select_target"
    assert target["target_type"] == "post"
    assert target["search"] == "${POST_TEXT}"
    assert target["required_keywords"] == ["${POST_TEXT}"]
    assert target["save_as"] == "_published_post_target"

    next_index = next(
        index
        for index, step in enumerate(flat_steps)
        if step.get("id") == "publish_post_next"
    )
    publish_index = next(
        index
        for index, step in enumerate(flat_steps)
        if step.get("id") == "publish_post_submit"
    )
    assert next_index < publish_index
    target_index = flat_steps.index(target)
    like_index = next(
        index
        for index, step in enumerate(flat_steps)
        if step.get("type") == "content_interaction"
        and step.get("action") == "like"
        and step.get("require_verified_target") == "_published_post_target"
    )
    comment_index = next(
        index
        for index, step in enumerate(flat_steps)
        if step.get("type") == "content_interaction"
        and step.get("action") == "comment"
        and step.get("require_verified_target") == "_published_post_target"
    )
    comment_step = flat_steps[comment_index]

    assert publish_index < target_index < like_index < comment_index
    assert comment_step["require_completion"] is True
    assert comment_step["completion_steps"][0]["text"] == "${COMMENT_TEXT}"


def test_login_template_opens_credential_form_from_saved_profile_chooser() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME["Đăng nhập Facebook"]
    login_branch = template["steps"][4]["else"]

    chooser = login_branch[0]
    assert chooser["type"] == "if_element"
    assert chooser["by"] == "content-desc"
    assert chooser["value"] == "Dùng trang cá nhân khác"
    assert chooser["then"][0] == {
        "type": "tap_selector",
        "by": "content-desc",
        "value": "Dùng trang cá nhân khác",
        "timeout": 4,
    }
    assert login_branch[1]["type"] == "login_if_needed"


def test_post_template_runs_real_like_and_comment() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[
        "Nuôi Facebook - Tương tác bài viết trên Feed"
    ]
    flat_steps = _walk_steps(template["steps"])
    scan = next(
        step for step in flat_steps if step.get("type") == "social_scan_posts_interact"
    )

    assert scan["require_comment"] is True
    assert scan["comment_text"] == "${COMMENT_TEXT}"
    assert scan["keywords"] == "${POST_KEYWORDS}"
    assert scan["target_count"] == "${POST_TARGET_COUNT}"


def test_home_post_commenter_connect_template_opens_comments_without_commenting() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[
        "Nuôi Facebook - Kết bạn từ người bình luận post Home đúng keyword"
    ]
    assert ScenarioModel.validate_dict(
        {"steps": template["steps"], "variables": template["variables"]}
    ) == []
    flat_steps = _walk_steps(template["steps"])
    scan = next(
        step for step in flat_steps if step.get("type") == "social_scan_posts_interact"
    )
    commenter_steps = [
        step
        for step in flat_steps
        if step.get("type") == "social_open_commenter_from_post_match"
    ]
    connection_steps = [
        step for step in flat_steps if step.get("type") == "connection_request"
    ]
    back_steps = [step for step in flat_steps if step.get("type") == "key" and step.get("key") == "back"]

    assert scan["target_count"] == "${POSTS_PER_BATCH}"
    assert scan["max_scrolls"] == 0
    assert scan["comment_text"] == ""
    assert scan["require_comment"] is False
    assert scan["like_post"] is False
    assert [step["action_index"] for step in commenter_steps] == [0, 1]
    assert all(step["platform"] == "facebook" for step in commenter_steps)
    assert all(step["source_var"] == "_post_scan" for step in commenter_steps)
    assert all(
        step["required_keywords"] == "${PROFILE_REQUIRED_KEYWORDS}"
        for step in commenter_steps
    )
    assert len(connection_steps) == 2
    assert all(step["require_verified_target"] == "_people_target" for step in connection_steps)
    assert len(back_steps) == 4


def _post_comment_sibling_flows(
    steps: list[dict[str, Any]],
) -> list[tuple[list[dict[str, Any]], int, int, int, int, int]]:
    flows: list[tuple[list[dict[str, Any]], int, int, int, int, int]] = []
    post_index = _first_step_index(steps, _is_fb_post_extract)
    find_index = _first_step_index(steps, lambda step: step.get("type") == "social_find_comment_button")
    tap_index = _first_step_index(steps, lambda step: step.get("type") == "social_tap_comment_target")
    filter_index = _first_step_index(steps, lambda step: step.get("type") == "social_apply_comment_filter")
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
    return step.get("type") == "extract" and step.get("entity") == "posts"


def _is_fb_comment_extract(step: dict[str, Any]) -> bool:
    return step.get("type") == "extract" and step.get("entity") == "comments"


def _is_back_step(step: dict[str, Any]) -> bool:
    return step.get("type") == "key" and step.get("key") == "back"


_SEED_TEMPLATE = "Nuôi Facebook - Gieo mầm bạn bè từ Group (account mới)"


def test_seed_template_never_uses_friend_suggestions() -> None:
    """A 0-friend account has no social graph, so "People you may know" is noise.

    Facebook builds that list from mutual friends; with none, it falls back to
    coarse signals and offers strangers. Sending there earns ignored requests —
    the exact signal that gets a new account restricted.
    """
    template = BUILTIN_TEMPLATE_BY_NAME[_SEED_TEMPLATE]
    flat_steps = _walk_steps(template["steps"])

    assert all(
        step.get("type") != "social_connect_visible_people" for step in flat_steps
    )
    # The friend request is issued on the person's own profile instead.
    assert any(
        step.get("type") == "social_open_commenter_from_post_match"
        for step in flat_steps
    )
    assert any(step.get("type") == "connection_request" for step in flat_steps)


def test_seed_template_interacts_before_connecting() -> None:
    """Presence in the group comes first; the request is what follows it.

    The scan step is not decoration: it puts the account in front of the people
    it is about to add, and it is what harvests the commenters in the first
    place.
    """
    template = BUILTIN_TEMPLATE_BY_NAME[_SEED_TEMPLATE]
    flat_steps = _walk_steps(template["steps"])
    types = [step.get("type") for step in flat_steps]

    scan_at = types.index("social_scan_posts_interact")
    connect_at = types.index("connection_request")
    assert scan_at < connect_at

    scan = flat_steps[scan_at]
    assert scan["like_post"] is True
    assert scan["require_comment"] is True
    assert scan["comment_text"] == "${COMMENT_TEXT}"


def test_seed_template_forbidden_keywords_keep_the_cold_start_signal() -> None:
    """"nhóm"/"trang" as forbidden terms would veto the only usable signal.

    Profile forbidden terms match as substrings over the whole profile text, so
    "nhóm" rejects every profile showing a shared group — the one piece of
    context a friendless account can manufacture — and "trang" rejects everyone
    named Trang.
    """
    template = BUILTIN_TEMPLATE_BY_NAME[_SEED_TEMPLATE]
    forbidden = template["variables"]["PROFILE_FORBIDDEN_KEYWORDS"]

    for token in ("nhóm", "group", "trang", "page"):
        assert token not in forbidden
    # Ads and anonymised rows are still worth excluding.
    assert "sponsored" in forbidden


def test_seed_template_joins_the_group_before_working_it() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[_SEED_TEMPLATE]
    flat_steps = _walk_steps(template["steps"])
    types = [step.get("type") for step in flat_steps]

    assert types.index("community_membership") < types.index(
        "social_scan_posts_interact"
    )
    join = next(s for s in flat_steps if s.get("type") == "community_membership")
    assert join["action"] == "join"
    # Already a member is the normal case, not a failure.
    assert join["ignore_error"] is True


def test_seed_template_passes_sequence_body_validator() -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[_SEED_TEMPLATE]

    async def _validate():
        return await validate_org_scenario_body(
            None,
            org_id="org",
            scenario_id="scenario",
            kind=ScenarioKind.SEQUENCE.value,
            body={
                "steps": template["steps"],
                "variables": template["variables"],
            },
        )

    result = asyncio.run(_validate())

    assert result.status == "valid", result.errors
    assert result.errors == []


def test_seed_template_returns_to_the_feed_before_each_group() -> None:
    """launch_app resumes Facebook wherever the last run stopped.

    Observed on a real device: a tap during search navigation opened a group
    photo fullscreen, and every selector afterwards missed — the run reported
    "group not found" when the truth was "we were never on the search screen".
    """
    template = BUILTIN_TEMPLATE_BY_NAME[_SEED_TEMPLATE]
    flat_steps = _walk_steps(template["steps"])
    types = [step.get("type") for step in flat_steps]

    resets = [
        step for step in flat_steps if str(step.get("id", "")).startswith(
            "seed_friends_return_to_feed"
        )
    ]
    assert resets, "no return-to-feed guard in the template"
    # Bounded: it must never be able to walk the account out of the app.
    assert len(resets) <= 3
    for reset in resets:
        assert reset["value"] == "Trang chủ"
        # Back is only pressed when the feed is NOT already visible.
        assert reset["then"] == []
        assert any(s.get("key") == "back" for s in reset["else"])

    reset_at = types.index("if_element")
    assert reset_at < types.index("tap_xml_match")


def test_connection_request_steps_carry_a_stable_id() -> None:
    """The durable ledger keys an action by step id and refuses claims without one.

    Observed on a real device: the request reached connection_request and then
    failed with "Enabled account action ledger requires execution id and stable
    step id" — so the send never happened.
    """
    for name in (
        _SEED_TEMPLATE,
        "Nuôi Facebook - Kết bạn từ người bình luận post Home đúng keyword",
    ):
        flat_steps = _walk_steps(BUILTIN_TEMPLATE_BY_NAME[name]["steps"])
        requests = [s for s in flat_steps if s.get("type") == "connection_request"]
        assert requests, f"{name} has no connection_request step"
        ids = [str(s.get("id") or "") for s in requests]
        assert all(ids), f"{name}: connection_request without an id"
        assert len(set(ids)) == len(ids), f"{name}: duplicate connection_request ids"
