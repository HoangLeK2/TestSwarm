"""Tests for execution_steps subtable and artifacts_json (DF-T-04-010 / DF-T-04-014)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from services.execution.step_store import (
    build_execution_step_payload,
    execution_step_to_legacy_dict,
    extract_artifacts_json,
    slim_step_result,
)
from services.campaign.dlq_service import _artifact_refs_from_steps


def test_payload_duration_ms_falls_back_to_step_result():
    """Finalize/checkpoint path never passes the kwarg — take it from the result."""
    payload = build_execution_step_payload(
        "exec-1",
        {"type": "tap", "id": "s1"},
        {"index": 0, "type": "tap", "ok": True, "duration_ms": 412.5},
    )
    assert payload["duration_ms"] == 412.5


def test_payload_duration_ms_falls_back_to_temporal_details_envelope():
    payload = build_execution_step_payload(
        "exec-1",
        {"type": "tap", "id": "s1"},
        {
            "index": 0,
            "type": "tap",
            "ok": True,
            "details": {"duration_ms": 900.0, "activity_duration_ms": 950.0},
        },
    )
    assert payload["duration_ms"] == 900.0


def test_payload_duration_ms_kwarg_wins_over_step_result():
    payload = build_execution_step_payload(
        "exec-1",
        {"type": "tap", "id": "s1"},
        {"index": 0, "type": "tap", "ok": True, "duration_ms": 412.5},
        duration_ms=10.0,
    )
    assert payload["duration_ms"] == 10.0


def test_extract_artifacts_json_from_workflow_details():
    workflow_entry = {
        "index": 1,
        "type": "tap",
        "ok": False,
        "message": "element not found",
        "details": {
            "artifacts_json": [{"type": "fail", "screenshot_url": "/captures/fail.png"}],
            "reason_code": "element_not_found",
        },
    }
    arts = extract_artifacts_json(workflow_entry)
    assert len(arts) == 1
    assert arts[0]["type"] == "fail"


def test_extract_step_artifacts_prefers_capture_step_metadata():
    from api.routes.executions import _extract_step_artifacts

    created_at = datetime(2026, 6, 23, tzinfo=timezone.utc)
    artifacts = _extract_step_artifacts(
        "exec-1",
        "10AE",
        [
            {
                "index": 0,
                "type": "run_scenario",
                "ok": False,
                "message": "run_scenario: child failed",
                "artifacts_json": [
                    {
                        "type": "fail",
                        "step_id": "tap-child",
                        "step_index": 3,
                        "step_type": "tap_selector",
                        "screenshot_url": "/captures/fail.png",
                    }
                ],
            }
        ],
        created_at,
    )

    assert len(artifacts) == 1
    assert artifacts[0].step_index == 3
    assert artifacts[0].step_type == "tap_selector"
    assert artifacts[0].metadata["step_id"] == "tap-child"
    assert artifacts[0].message is None


def test_extract_step_artifacts_uses_nested_step_message_for_child_metadata():
    from api.routes.executions import _extract_step_artifacts

    created_at = datetime(2026, 6, 23, tzinfo=timezone.utc)
    artifacts = _extract_step_artifacts(
        "exec-1",
        "10AE",
        [
            {
                "index": 0,
                "type": "run_scenario",
                "ok": False,
                "message": "run_scenario: sub-scenario 'child' failed",
                "artifacts_json": [
                    {
                        "type": "fail",
                        "step_index": 0,
                        "step_type": "scroll_to",
                        "screenshot_url": "/captures/scroll-fail.png",
                    }
                ],
                "sub_result": {
                    "step_results": [
                        {
                            "index": 0,
                            "type": "scroll_to",
                            "ok": False,
                            "message": "scroll_to text='codex' not found after 5 swipes",
                        }
                    ]
                },
            }
        ],
        created_at,
    )

    assert len(artifacts) == 1
    assert artifacts[0].step_index == 0
    assert artifacts[0].step_type == "scroll_to"
    assert artifacts[0].message == "scroll_to text='codex' not found after 5 swipes"


def test_artifact_context_merge_recovers_nested_run_scenario_artifacts():
    from api.routes.executions import (
        _extract_step_artifacts,
        _merge_step_artifact_context,
    )

    persisted_steps = [
        {
            "index": 0,
            "type": "run_scenario",
            "ok": False,
            "message": "run_scenario: child failed",
            "artifacts_json": [],
            "artifacts": [],
        }
    ]
    result_steps = [
        {
            "index": 0,
            "type": "run_scenario",
            "ok": False,
            "sub_result": {
                "step_results": [
                    {
                        "index": 2,
                        "type": "tap_selector",
                        "ok": False,
                        "message": "not found",
                        "artifacts_json": [
                            {
                                "type": "fail",
                                "step_id": "tap-child",
                                "step_index": 2,
                                "step_type": "tap_selector",
                                "screenshot_url": "/captures/child-fail.png",
                            }
                        ],
                    }
                ]
            },
        }
    ]

    merged_steps = _merge_step_artifact_context(persisted_steps, result_steps)
    artifacts = _extract_step_artifacts(
        "exec-1",
        "10AE",
        merged_steps,
        datetime(2026, 6, 23, tzinfo=timezone.utc),
    )

    assert len(artifacts) == 1
    assert artifacts[0].step_index == 2
    assert artifacts[0].step_type == "tap_selector"
    assert artifacts[0].message == "not found"
    assert artifacts[0].url == "/captures/child-fail.png"


def test_slim_step_result_strips_nested_details_artifacts():
    slim = slim_step_result(
        {
            "index": 1,
            "type": "tap",
            "ok": False,
            "message": "fail",
            "details": {
                "artifacts_json": [{"type": "fail"}],
                "reason_code": "timeout",
            },
        }
    )
    assert "artifacts_json" not in slim.get("details", {})
    assert slim["details"]["reason_code"] == "timeout"


def test_build_execution_step_payload_omits_empty_artifacts_key():
    payload = build_execution_step_payload(
        "exec-1",
        {"type": "wait"},
        {"index": 0, "type": "wait", "ok": True, "details": {"message": "ok"}},
    )
    assert "artifacts_json" not in payload


def test_dlq_refs_from_workflow_details_shape():
    step_results = [
        {
            "index": 2,
            "type": "tap_selector",
            "ok": False,
            "message": "not found",
            "details": {
                "artifacts": [
                    {
                        "type": "fail",
                        "screenshot_url": "http://minio/fail.jpg",
                        "hierarchy_url": "http://minio/fail.xml",
                    }
                ],
            },
        }
    ]
    refs = _artifact_refs_from_steps(step_results)
    assert refs["screenshot_fail"] == "http://minio/fail.jpg"
    assert refs["hierarchy_url"] == "http://minio/fail.xml"


@pytest.mark.asyncio
async def test_finalize_bulk_upsert_does_not_wipe_existing_artifacts(session_factory):
    from datetime import datetime, timezone

    from db.crud.execution import create_execution
    from db.crud.execution_steps import get_execution_step, upsert_execution_step
    from db.models import Organization, User
    from services.execution.step_store import persist_execution_steps_from_results
    from tenancy.context import set_current_org_id

    NOW = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            Organization(
                id="org-steps-guard",
                business_name="Guard Org",
                business_email="guard@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id="user-steps-guard",
                email="guard@test.com",
                name="Guard User",
                hashed_password="x",
                org_id="org-steps-guard",
            )
        )
        await db.flush()
        set_current_org_id("org-steps-guard")
        execution = await create_execution(db, run_type="campaign_run", user_id="user-steps-guard")
        await upsert_execution_step(
            db,
            execution_id=execution.id,
            step_index=0,
            status="passed",
            artifacts_json=[{"type": "post", "screenshot_url": "/captures/post.png"}],
        )
        exec_id = execution.id
        await db.commit()

    async with session_factory() as db:
        await persist_execution_steps_from_results(
            db,
            execution_id=exec_id,
            step_results=[
                {
                    "index": 0,
                    "type": "wait",
                    "ok": True,
                    "message": "ok",
                    "details": {},
                }
            ],
            default_ended_at=NOW,
        )
        await db.commit()

    async with session_factory() as db:
        row = await get_execution_step(db, exec_id, 0)
        assert row is not None
        assert row.artifacts_json[0]["screenshot_url"] == "/captures/post.png"


def test_extract_artifacts_json_prefers_artifacts_json():
    arts = [{"type": "pre", "screenshot_url": "/captures/a.png"}]
    result = {"artifacts_json": arts, "artifacts": [{"type": "post"}]}
    assert extract_artifacts_json(result) == arts


def test_slim_step_result_strips_artifact_blobs():
    slim = slim_step_result(
        {
            "index": 0,
            "type": "wait",
            "ok": True,
            "artifacts_json": [{"type": "pre"}],
            "screenshot_pre": {"full": "/x.png"},
            "message": "ok",
        }
    )
    assert "artifacts_json" not in slim
    assert "screenshot_pre" not in slim
    assert slim["message"] == "ok"


def test_build_execution_step_payload_maps_fields():
    step = {"id": "s1", "type": "wait", "seconds": 1}
    result = {
        "index": 2,
        "type": "wait",
        "ok": False,
        "message": "timeout",
        "reason_code": "timeout",
        "failure_class": "system_timeout",
        "retry_hint": "retry_if_policy_allows",
        "operator_summary": "system_timeout",
        "retry_attempts": [{"attempt": 1, "error_reason": "timeout", "wait_ms_before_next": 500}],
        "artifacts_json": [{"type": "fail", "screenshot_url": "/captures/f.png"}],
    }
    payload = build_execution_step_payload("exec-1", step, result)
    assert payload["execution_id"] == "exec-1"
    assert payload["step_index"] == 2
    assert payload["step_id"] == "s1"
    assert payload["status"] == "failed"
    assert payload["artifacts_json"][0]["type"] == "fail"
    assert payload["attempts_json"][0]["attempt"] == 1
    assert payload["error_json"]["reason_code"] == "timeout"
    assert payload["error_json"]["failure_class"] == "system_timeout"
    assert payload["error_json"]["retry_hint"] == "retry_if_policy_allows"
    assert payload["error_json"]["operator_summary"] == "system_timeout"
    assert payload["effective_config_json"]["step_id"] == "s1"


def test_unannotated_failure_is_classified_before_it_reaches_error_json():
    """Most failure paths hand-build {index,type,ok,message} and never call
    annotate_step_failure — the touch-primitive fast path, the activity-raised
    path in _flush_batch, and every control-flow entry. error_json used to
    arrive holding nothing but `message`, so failure_class was unqueryable."""
    payload = build_execution_step_payload(
        "exec-1",
        {"id": "s9", "type": "tap_selector"},
        {
            "index": 9,
            "type": "tap_selector",
            "ok": False,
            "message": "selector text='Nhóm' not found, no fallback position",
        },
    )
    assert payload["error_json"]["failure_class"] == "business_selector_miss"
    assert payload["error_json"]["reason_code"] == "selector_not_found"


def test_no_control_channel_classifies_as_device_lost():
    payload = build_execution_step_payload(
        "exec-1",
        {"type": "open_url"},
        {
            "index": 0,
            "type": "open_url",
            "ok": False,
            "message": "open_url: no control channel available for serial=ABC",
        },
    )
    assert payload["error_json"]["failure_class"] == "device_lost"


def test_stale_ok_reason_code_does_not_survive_on_a_failed_step():
    # extraction.py defaults its diagnostic reason_code to "ok"; 15 failed rows
    # carried it into the DB, where it means nothing.
    payload = build_execution_step_payload(
        "exec-1",
        {"type": "fb_tap_comment_button"},
        {
            "index": 3,
            "type": "fb_tap_comment_button",
            "ok": False,
            "message": "comment button not tappable",
            "reason_code": "ok",
        },
    )
    assert payload["error_json"].get("reason_code") != "ok"
    assert payload["error_json"]["failure_class"] == "unknown"


def test_passed_step_is_not_classified():
    payload = build_execution_step_payload(
        "exec-1", {"type": "wait"}, {"index": 0, "type": "wait", "ok": True}
    )
    assert payload["error_json"] == {}


def test_failed_execution_step_payload_keeps_nested_extra_data_diagnostic():
    step = {"id": "run-child", "type": "run_scenario", "scenario_id": "child-1"}
    result = {
        "index": 1,
        "type": "run_scenario",
        "ok": False,
        "message": "run_scenario failed: edge extra_data failed",
        "edge_extra_summary": {
            "diagnostic": {
                "reason_code": "post_open_target_not_found",
                "timing": {"total_ms": 42.0},
            }
        },
        "nested_failure": {
            "step_index": 0,
            "step_type": "extract",
            "message": "edge extra_data failed",
        },
        "extra_data_total_ms": 42.0,
    }

    payload = build_execution_step_payload("exec-1", step, result)

    assert payload["status"] == "failed"
    assert payload["error_json"]["edge_extra_summary"]["diagnostic"]["reason_code"] == (
        "post_open_target_not_found"
    )
    assert payload["error_json"]["edge_extra_summary"]["diagnostic"]["timing"]["total_ms"] == 42.0
    assert payload["error_json"]["nested_failure"]["step_type"] == "extract"
    assert payload["error_json"]["extra_data_total_ms"] == 42.0


def test_ignored_run_scenario_failure_persists_as_passed_step():
    step = {"id": "run-child", "type": "run_scenario", "scenario_id": "child-1"}
    result = {
        "index": 1,
        "type": "run_scenario",
        "ok": True,
        "message": "run_scenario failed; ignored by parent run_scenario policy",
        "error_policy": "continue",
        "error_ignored": True,
        "marked_ignored": True,
        "ignored_failure": True,
        "sub_result": {
            "success": False,
            "step_results": [
                {"index": 0, "type": "tap_selector", "ok": False, "message": "not found"}
            ],
        },
    }
    payload = build_execution_step_payload("exec-1", step, result)
    assert payload["status"] == "passed"
    assert payload["marked_ignored"] is True
    assert payload["error_json"] == {}


def test_temporal_finalize_extracts_ignored_step_warnings():
    from temporal.activities import _ignored_step_warnings_from_results

    warnings = _ignored_step_warnings_from_results(
        [
            {"index": 0, "type": "tap", "ok": True},
            {
                "index": 1,
                "type": "run_scenario",
                "ok": True,
                "ignored_failure": True,
                "ignored_message": (
                    "run_scenario: sub-scenario 'child' failed — "
                    "incident recovery playbooks did not resolve the step"
                ),
            },
        ]
    )

    assert warnings == [
        {
            "step_index": 1,
            "step_type": "run_scenario",
            "message": (
                "run_scenario: sub-scenario 'child' failed — "
                "incident recovery playbooks did not resolve the step"
            ),
        }
    ]


def test_extract_artifacts_json_from_temporal_details():
    arts = [{"type": "post", "screenshot_url": "/captures/post.png"}]
    result = {
        "index": 1,
        "type": "tap",
        "ok": True,
        "details": {"artifacts_json": arts},
    }
    assert extract_artifacts_json(result) == arts


@pytest.mark.asyncio
async def test_upsert_preserves_artifacts_on_empty_finalize(session_factory):
    from datetime import datetime, timezone

    from db.crud.execution import create_execution
    from db.crud.execution_steps import get_execution_step, upsert_execution_step
    from db.models import Organization, User
    from tenancy.context import set_current_org_id

    NOW = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            Organization(
                id="org-steps-preserve",
                business_name="Preserve Org",
                business_email="preserve@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id="user-steps-preserve",
                email="preserve@test.com",
                name="Preserve User",
                hashed_password="x",
                org_id="org-steps-preserve",
            )
        )
        await db.flush()
        set_current_org_id("org-steps-preserve")
        execution = await create_execution(db, run_type="campaign_run", user_id="user-steps-preserve")
        arts = [{"type": "pre", "screenshot_url": "/captures/pre.png"}]
        await upsert_execution_step(
            db,
            execution_id=execution.id,
            step_index=0,
            status="passed",
            step_type="wait",
            artifacts_json=arts,
        )
        await upsert_execution_step(
            db,
            execution_id=execution.id,
            step_index=0,
            status="passed",
            step_type="wait",
            artifacts_json=[],
        )
        exec_id = execution.id
        await db.commit()

    async with session_factory() as db:
        row = await get_execution_step(db, exec_id, 0)
        assert row is not None
        assert row.artifacts_json == arts


@pytest.mark.asyncio
async def test_upsert_execution_step_roundtrip(session_factory):
    from datetime import datetime, timezone

    from db.crud.execution import create_execution
    from db.crud.execution_steps import get_execution_step, list_execution_steps, upsert_execution_step
    from db.models import Organization, User
    from tenancy.context import set_current_org_id

    NOW = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            Organization(
                id="org-steps",
                business_name="Steps Org",
                business_email="steps@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id="user-steps",
                email="steps@test.com",
                name="Steps User",
                hashed_password="x",
                org_id="org-steps",
            )
        )
        await db.flush()

        set_current_org_id("org-steps")
        execution = await create_execution(db, run_type="campaign_run", user_id="user-steps")
        now = datetime.now(timezone.utc)
        await upsert_execution_step(
            db,
            execution_id=execution.id,
            step_index=0,
            status="passed",
            step_id="step-a",
            step_type="wait",
            started_at=now,
            ended_at=now,
            duration_ms=12.5,
            artifacts_json=[{"type": "pre", "screenshot_url": "/captures/pre.png"}],
            effective_config_json={"step_id": "step-a", "seconds": 1},
        )
        exec_id = execution.id
        await db.commit()

    async with session_factory() as db:
        row = await get_execution_step(db, exec_id, 0)
        assert row is not None
        assert row.artifacts_json[0]["type"] == "pre"
        rows = await list_execution_steps(db, exec_id)
        assert len(rows) == 1
        legacy = execution_step_to_legacy_dict(row)
        assert legacy["artifacts_json"][0]["screenshot_url"] == "/captures/pre.png"


@pytest.mark.asyncio
async def test_persist_execution_steps_from_results(session_factory):
    from datetime import datetime, timezone

    from db.crud.execution import create_execution
    from db.crud.execution_steps import list_execution_steps
    from db.models import Organization, User
    from services.execution.step_store import persist_execution_steps_from_results
    from tenancy.context import set_current_org_id

    NOW = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            Organization(
                id="org-steps-bulk",
                business_name="Bulk Org",
                business_email="bulk@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id="user-steps-bulk",
                email="bulk@test.com",
                name="Bulk User",
                hashed_password="x",
                org_id="org-steps-bulk",
            )
        )
        await db.flush()
        set_current_org_id("org-steps-bulk")
        execution = await create_execution(db, run_type="campaign_run", user_id="user-steps-bulk")
        await persist_execution_steps_from_results(
            db,
            execution_id=execution.id,
            step_results=[
                {
                    "index": 0,
                    "type": "wait",
                    "ok": True,
                    "artifacts_json": [{"type": "post", "screenshot_url": "/captures/post.png"}],
                }
            ],
            default_ended_at=NOW,
        )
        exec_id = execution.id
        await db.commit()

    async with session_factory() as db:
        rows = await list_execution_steps(db, exec_id)
        assert len(rows) == 1
        assert rows[0].artifacts_json[0]["type"] == "post"
