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
            "type": "connection_request",
            "platform": "facebook",
            "save_as": "FRIEND_RESULT",
        },
        {
            "type": "community_membership",
            "platform": "facebook",
            "save_as": "GROUP_RESULT",
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


@pytest.mark.parametrize(
    "step_type",
    ["content_interaction", "connection_request", "community_membership"],
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
