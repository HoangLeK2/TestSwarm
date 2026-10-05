"""Authored-step ids must hold at every depth, not just at the root.

Root-only validation is what let a nested `connection_request` ship without an
id. On a real device the send reached the step and then failed with "Enabled
account action ledger requires execution id and stable step id" — the friend
request never went out, and nothing in the template or the tests said so.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from db.models.enums import ScenarioKind
from db.seeds.scenario_templates import BUILTIN_TEMPLATE_BY_NAME
from services.scenario_dsl.body_validator import validate_org_scenario_body
from services.scenario_dsl.step_tree import (
    assign_missing_step_ids,
    find_duplicate_step_ids,
    find_steps_missing_id,
    iter_authored_steps,
)

# Templates that have been through id hardening. A template only joins this list
# once every authored step in it carries a stable id.
HARDENED_TEMPLATES = (
    "Nuôi Instagram - Gieo mầm bạn bè từ Group (account mới)",
    "Nuôi Instagram - Kết bạn từ người bình luận post Home đúng keyword",
)


def _validate(body: dict[str, Any]):
    return asyncio.run(
        validate_org_scenario_body(
            None,
            org_id="org",
            scenario_id="scenario",
            kind=ScenarioKind.SEQUENCE.value,
            body=body,
        )
    )


def test_traversal_reaches_loop_branch_and_completion_children() -> None:
    steps = [
        {
            "id": "root_loop",
            "type": "loop",
            "steps": [
                {
                    "id": "root_loop_branch",
                    "type": "if_variable",
                    "then": [{"id": "then_child", "type": "wait"}],
                    "else": [{"id": "else_child", "type": "wait"}],
                },
                {
                    "id": "root_loop_pick",
                    "type": "random_pick",
                    "branches": [
                        {"weight": 3, "steps": [{"id": "branch_child", "type": "wait"}]}
                    ],
                },
                {
                    "id": "root_loop_comment",
                    "type": "content_interaction",
                    "completion_steps": [{"id": "completion_child", "type": "input_text"}],
                    "completion_verify": {"id": "verify_child", "type": "wait_element"},
                },
            ],
        }
    ]

    found = {item.step_id: item.depth for item in iter_authored_steps(steps)}

    assert found == {
        "root_loop": 0,
        "root_loop_branch": 1,
        "then_child": 2,
        "else_child": 2,
        "root_loop_pick": 1,
        "branch_child": 2,
        "root_loop_comment": 1,
        "completion_child": 2,
        "verify_child": 2,
    }


def test_traversal_ignores_objects_that_are_not_authored_steps() -> None:
    """A branch wrapper and a login recipe have no `type` and no place for an id.

    Demanding one from them would report failures a human cannot fix.
    """
    steps = [
        {
            "id": "login",
            "type": "login_if_needed",
            # Config, not a step tree — must not be walked into.
            "profile": {
                "login_recipe": {
                    "fields": {"username": {"value_from": "account.username"}},
                    "steps": [{"selector": "username"}],
                }
            },
            "config": {"steps": [{"type": "wait"}]},
        },
        {
            "id": "pick",
            "type": "random_pick",
            # The branch dict itself carries a weight, not a type.
            "branches": [{"weight": 1, "steps": []}],
        },
        # A list entry with no type is not a step either.
        {"note": "not a step"},
    ]

    assert [item.step_id for item in iter_authored_steps(steps)] == ["login", "pick"]
    assert find_steps_missing_id(steps) == []


def test_missing_nested_id_is_reported_with_its_location() -> None:
    steps = [
        {
            "id": "gate",
            "type": "if_variable",
            "then": [
                {
                    "id": "cycle",
                    "type": "loop",
                    "steps": [{"type": "connection_request", "platform": "instagram"}],
                }
            ],
            "else": [],
        }
    ]

    missing = find_steps_missing_id(steps)

    assert [(item.location, item.step_type, item.depth) for item in missing] == [
        ("steps[0].then[0].steps[0]", "connection_request", 2)
    ]


def test_duplicate_nested_ids_are_reported_with_every_location() -> None:
    steps = [
        {
            "id": "cycle",
            "type": "loop",
            "steps": [
                {"id": "connect", "type": "connection_request"},
                {
                    "id": "second",
                    "type": "if_variable",
                    "then": [{"id": "connect", "type": "connection_request"}],
                    "else": [],
                },
            ],
        }
    ]

    assert find_duplicate_step_ids(steps) == {
        "connect": ["steps[0].steps[0]", "steps[0].steps[1].then[0]"]
    }


def test_validator_rejects_a_duplicate_id_hidden_inside_a_branch() -> None:
    """Two sends under one id are one ledger action; the second is dropped."""
    result = _validate(
        {
            "steps": [
                {
                    "id": "cycle",
                    "type": "loop",
                    "steps": [
                        {"id": "connect", "type": "connection_request"},
                        {
                            "id": "guard",
                            "type": "if_variable",
                            "then": [{"id": "connect", "type": "connection_request"}],
                            "else": [],
                        },
                    ],
                }
            ]
        }
    )

    assert result.status == "invalid"
    duplicates = [e for e in result.errors if e.code == "DUPLICATE_STEP_ID"]
    assert [e.details["step_id"] for e in duplicates] == ["connect"]
    assert duplicates[0].details["locations"] == [
        "steps[0].steps[0]",
        "steps[0].steps[1].then[0]",
    ]


def test_validator_fills_a_missing_id_instead_of_rejecting_the_body() -> None:
    """A body without ids is normalized, not refused — from any ingress.

    Only the flow editor ever minted ids. An imported body, a seeded builtin and
    an AI-compiled scenario all arrive without them, and the ledger refuses a
    claim from a step with no id.
    """
    body = {
        "steps": [
            {
                "id": "gate",
                "type": "if_variable",
                "then": [{"type": "wait", "seconds": 1}],
                "else": [],
            },
            {"type": "key", "key": "home"},
        ]
    }

    result = _validate(body)

    assert result.status == "valid", [e.to_dict() for e in result.errors]
    steps = result.normalized_body["steps"]
    assert steps[0]["then"][0]["id"] == "gate__then_0"
    assert steps[1]["id"] == "step_1"
    assert find_steps_missing_id(steps) == []


def test_filled_ids_are_derived_the_same_way_every_run() -> None:
    """Structural, never random — a builtin is re-seeded from code on each boot.

    A random id would rename the same step on every deploy, which is the exact
    instability an id exists to prevent.
    """
    body = {
        "steps": [
            {
                "id": "cycle",
                "type": "loop",
                "steps": [
                    {"type": "connection_request"},
                    {
                        "type": "random_pick",
                        "branches": [{"weight": 1, "steps": [{"type": "wait"}]}],
                    },
                ],
            }
        ]
    }

    first = assign_missing_step_ids(body["steps"])
    second = assign_missing_step_ids(body["steps"])

    assert first == second
    # Idempotent: feeding the result back changes nothing.
    assert assign_missing_step_ids(first) == first
    # And the input was not mutated.
    assert "id" not in body["steps"][0]["steps"][0]

    assert first[0]["steps"][0]["id"] == "cycle__steps_0"
    assert first[0]["steps"][1]["branches"][0]["steps"][0]["id"] == (
        "cycle__steps_1__branch0_0"
    )


def test_a_derived_id_never_steals_an_id_an_author_already_used() -> None:
    steps = [
        {"id": "step_0", "type": "wait"},
        {"type": "key", "key": "home"},
    ]

    filled = assign_missing_step_ids(steps)

    assert [step["id"] for step in filled] == ["step_0", "step_1"]

    collided = assign_missing_step_ids(
        [{"id": "step_1", "type": "wait"}, {"type": "key", "key": "home"}]
    )
    assert [step["id"] for step in collided] == ["step_1", "step_1_2"]


def test_filling_ids_leaves_non_step_objects_alone() -> None:
    steps = [
        {
            "type": "login_if_needed",
            "profile": {"login_recipe": {"steps": [{"selector": "username"}]}},
        }
    ]

    filled = assign_missing_step_ids(steps)

    assert filled[0]["id"] == "step_0"
    assert filled[0]["profile"] == {
        "login_recipe": {"steps": [{"selector": "username"}]}
    }


@pytest.mark.parametrize("template_name", HARDENED_TEMPLATES)
def test_hardened_templates_carry_a_stable_id_on_every_authored_step(
    template_name: str,
) -> None:
    template = BUILTIN_TEMPLATE_BY_NAME[template_name]

    missing = find_steps_missing_id(template["steps"])

    assert missing == [], [(item.location, item.step_type) for item in missing]
    assert find_duplicate_step_ids(template["steps"]) == {}


@pytest.mark.parametrize("template_name", HARDENED_TEMPLATES)
def test_hardened_templates_need_no_derived_ids(template_name: str) -> None:
    """Nothing in these two templates falls back to a generated id.

    A hardened template is one where every id was chosen by a human, so the ids
    survive a step being inserted above them — which a derived id does not.
    """
    template = BUILTIN_TEMPLATE_BY_NAME[template_name]
    body = {"steps": template["steps"], "variables": template["variables"]}

    result = _validate(body)

    assert result.status == "valid", [e.to_dict() for e in result.errors]
    # Nothing to fill: the fill pass is a no-op on these two.
    assert assign_missing_step_ids(template["steps"]) == template["steps"]


def test_every_builtin_template_is_seeded_with_ids_at_every_depth() -> None:
    """The seeded row is what a campaign runs, and the ledger needs the ids."""
    from db.seeds.scenario_templates import _seedable_steps

    for name, template in BUILTIN_TEMPLATE_BY_NAME.items():
        seeded = _seedable_steps(template.get("steps") or [])
        assert find_steps_missing_id(seeded) == [], name
        assert find_duplicate_step_ids(seeded) == {}, name
        # Deterministic across restarts: the row is rewritten from code on boot.
        assert _seedable_steps(template.get("steps") or []) == seeded, name


def test_no_builtin_template_repeats_a_step_id_at_any_depth() -> None:
    """Applies to every template, hardened or not — a duplicate is always a bug."""
    offenders = {
        name: find_duplicate_step_ids(template.get("steps") or [])
        for name, template in BUILTIN_TEMPLATE_BY_NAME.items()
        if find_duplicate_step_ids(template.get("steps") or [])
    }

    assert offenders == {}
