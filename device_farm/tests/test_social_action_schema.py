from __future__ import annotations

import pytest

from api.schemas.scenario import ScenarioModel


@pytest.mark.parametrize(
    "step",
    [
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "like",
            "save_as": "LIKE_RESULT",
        },
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "comment",
            "save_as": "COMMENT_RESULT",
        },
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "share",
            "require_completion": True,
            "completion_steps": [{"type": "key", "key": "back"}],
            "save_as": "SHARE_RESULT",
        },
        {
            "type": "lease_connection_candidate",
            "platform": "facebook",
        },
        {
            "type": "connection_request",
            "platform": "facebook",
            "require_verified_target": "_people_target",
            "candidate_entity_id": "${TARGET_ENTITY_ID}",
            "require_candidate_status": "ready_to_connect",
            "candidate_lease_token": "${CANDIDATE_LEASE_TOKEN}",
            "save_as": "FRIEND_RESULT",
        },
        {
            "type": "community_membership",
            "platform": "facebook",
            "save_as": "GROUP_RESULT",
        },
        {
            "type": "fb_select_people_profile",
            "search": "Hoang Le",
            "display_name": "Hoang Le",
            "required_keywords": ["Hoang Le"],
            "save_as": "_people_target",
            "save_success_as": "PEOPLE_PROFILE_SELECTED",
            "skip_candidate_on_not_verified": True,
            "candidate_entity_id": "${TARGET_ENTITY_ID}",
            "candidate_lease_token": "${CANDIDATE_LEASE_TOKEN}",
            "skip_candidate_defer_hours": 24,
        },
        {
            "type": "fb_connect_visible_people",
            "platform": "facebook",
            "min_score": "${CONNECTION_MIN_COMMON_SCORE}",
            "require_common": True,
            "common_keywords": "${CONNECTION_COMMON_KEYWORDS}",
            "forbidden_keywords": ["trang", "page", "anonymous"],
            "save_as": "_visible_connection_action",
        },
        {
            "type": "fb_select_post_target",
            "search": "launch text",
            "display_text": "launch text",
            "required_keywords": ["launch text"],
            "save_as": "_post_target",
        },
        {
            "type": "social_open_author_from_post_match",
            "platform": "facebook",
            "source_var": "_post_scan",
            "action_index": 0,
            "required_keywords": ["AI"],
            "optional_keywords": ["automation"],
            "forbidden_keywords": ["page", "group"],
            "save_as": "_people_target",
            "save_success_as": "PEOPLE_PROFILE_SELECTED",
            "save_opened_as": "AUTHOR_PROFILE_OPENED",
        },
        {
            "type": "social_open_commenter_from_post_match",
            "platform": "facebook",
            "source_var": "_post_scan",
            "action_index": 0,
            "required_keywords": ["AI"],
            "optional_keywords": ["automation"],
            "forbidden_keywords": ["page", "group"],
            "max_commenters": 5,
            "save_as": "_people_target",
            "save_success_as": "PEOPLE_PROFILE_SELECTED",
            "save_opened_as": "COMMENTER_PROFILE_OPENED",
            "save_sheet_opened_as": "COMMENT_SHEET_OPENED",
        },
    ],
)
def test_generic_social_action_steps_are_valid_scenario_steps(step: dict) -> None:
    assert ScenarioModel.validate_dict({"steps": [step]}) == []


def test_social_action_step_rejects_invalid_timing() -> None:
    errors = ScenarioModel.validate_dict(
        {
            "steps": [
                {
                    "type": "connection_request",
                    "platform": "facebook",
                    "poll": 0,
                }
            ]
        }
    )

    assert errors
    assert any("poll" in error for error in errors)


def test_social_action_step_limits_completion_steps() -> None:
    errors = ScenarioModel.validate_dict(
        {
            "steps": [
                {
                    "type": "content_interaction",
                    "action": "comment",
                    "require_completion": True,
                    "completion_steps": [
                        {"type": "key", "key": "back"} for _ in range(9)
                    ],
                }
            ]
        }
    )

    assert errors
    assert any("completion_steps" in error for error in errors)


@pytest.mark.parametrize(
    "step_type",
    [
        "content_interaction",
        "connection_request",
        "lease_connection_candidate",
        "community_membership",
        "fb_select_people_profile",
        "fb_connect_visible_people",
        "fb_select_post_target",
        "social_open_author_from_post_match",
        "social_open_commenter_from_post_match",
    ],
)
def test_generic_social_steps_keep_account_binding_warning(step_type: str) -> None:
    from services.campaign.account_resolver import scenario_requires_account
    from services.execution.preview_introspection import preview_requires_account
    from services.org_scenario_validation.step_index import OrgStepIndex
    from services.scenario_validation.step_index import StepIndex

    steps = [{"id": "social-1", "type": step_type, "platform": "facebook"}]

    assert StepIndex.build(steps).has_social is True
    assert OrgStepIndex.build(steps).has_social is True
    assert scenario_requires_account(steps) is True
    assert preview_requires_account(steps) is True
