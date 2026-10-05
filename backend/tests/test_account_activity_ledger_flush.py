"""End-to-end: scenario steps -> buffered entries -> real rows in account_actions.

Everything below the buffer was previously only exercised with a mocked writer.
This runs the real path: tenant resolution, the unique action_key, the
transition and attempt tables. The only fake is the phone.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from db.models.account import Account
from db.models.account_action import (
    AccountAction,
    AccountActionAttempt,
    AccountActionTransition,
)
from db.models.execution import Execution
from db.models.organization import Organization
from services.account_actions.coordinator import _record_applied_actions
from tasks.scenario.context import ScenarioContext
from tasks.scenario.executor import ScenarioExecutor
from tasks.scenario.steps import register_step
from tenancy.context import tenant_context

pytest_plugins = ["tests.tenancy_test_support"]

ORG = "org-activity"
ACCOUNT = "account-activity"
EXECUTION = "execution-activity"


@register_step("_activity_probe")
def _probe(sc, step, idx, result):
    """Stand-in for a real handler.

    It reports the target it resolved *before* acting, then succeeds or fails —
    the shape social_actions has, where prepare_action claims a named target and
    the tap afterwards is what can go wrong.
    """
    if step.get("_entity_id"):
        result["external_entity_id"] = step["_entity_id"]
    if step.get("_fail"):
        result["ok"] = False
        result["message"] = "probe: element not visible"
        result["reason_code"] = "ELEMENT_NOT_FOUND"
        return
    result["message"] = "probe ok"


class _FakeDevice:
    serial = "PHONE-ACTIVITY"
    model = "SM-X"
    screen_width = 1080
    screen_height = 2400
    _loop = None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add(
            Organization(
                id=ORG,
                business_name="Activity org",
                business_email="activity@example.com",
            )
        )
        db.add(
            Account(
                id=ACCOUNT,
                org_id=ORG,
                platform="instagram",
                username="activity-user",
                display_name="Alice",
            )
        )
        db.add(
            Execution(
                id=EXECUTION,
                org_id=ORG,
                account_id=ACCOUNT,
                run_type="campaign",
            )
        )
        await db.commit()


async def _read(session_factory, stmt):
    """Read back under the tenant scope the runtime would have set."""
    async with session_factory() as db:
        with tenant_context(ORG):
            return (await db.execute(stmt)).scalars().all()


async def _flush(session_factory, entries: list[dict]) -> None:
    async with session_factory() as db:
        await _record_applied_actions(
            db,
            identity=entries[0]["identity"],
            action_type=entries[0]["action_type"],
            platform="instagram",
            entries=entries,
            reason="scenario_step",
            observe=False,
            reserved_action_id=None,
        )
        await db.commit()


def _scenario(steps: list[dict]) -> dict:
    return {
        "capability_preflight": False,
        "execution_id": EXECUTION,
        "_campaign_id": "campaign-activity",
        "_campaign_vars": {
            "__ACCOUNT_ID__": ACCOUNT,
            "__ACCOUNT_DISPLAY_NAME__": "Alice",
            "__ACCOUNT_PLATFORM__": "instagram",
        },
        "steps": steps,
    }


def _buffer_entries(monkeypatch, steps: list[dict]) -> list[dict]:
    """Run the real executor and return what it queued for the ledger."""
    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "enabled")
    captured: list[dict] = []
    import tasks.scenario.executor as executor_module

    monkeypatch.setattr(
        executor_module,
        "_flush_ledger_entries",
        lambda sc: captured.extend(sc.pending_ledger_entries),
    )
    sc = ScenarioContext.from_args(_FakeDevice(), _scenario(steps))
    ScenarioExecutor(sc).run()
    return captured


STEPS = [
    {
        "type": "_activity_probe",
        "id": "open-app",
        "package": "com.instagram.android",
        "semantic_action": "app.open",
    },
    {
        "type": "_activity_probe",
        "id": "open-post",
        "_entity_id": "post-77",
        "semantic_action": "post.open",
    },
    {
        "type": "_activity_probe",
        "id": "add-friend",
        "_entity_id": "person-12",
        "_fail": True,
        "semantic_action": "connection.request",
    },
]


@pytest.mark.asyncio
async def test_buffered_actions_become_rows_with_per_step_identity(
    tenancy_session_factory, monkeypatch
):
    await _seed(tenancy_session_factory)
    entries = _buffer_entries(monkeypatch, STEPS)
    assert len(entries) == 3

    await _flush(tenancy_session_factory, entries)

    rows = await _read(
        tenancy_session_factory,
        select(AccountAction)
        .where(AccountAction.org_id == ORG)
        .order_by(AccountAction.step_id),
    )
    by_step = {row.step_id: row for row in rows}

    # Each entry keeps its own step and action type. Before the per-entry
    # override in _record_applied_actions, all three landed under "open-app"
    # with action_type app.open.
    assert set(by_step) == {"open-app", "open-post", "add-friend"}
    assert by_step["open-app"].action_type == "app.open"
    assert by_step["open-post"].action_type == "post.open"
    assert by_step["add-friend"].action_type == "connection.request"

    assert by_step["open-app"].target["target_id"] == "com.instagram.android"
    assert by_step["open-post"].target["target_id"] == "post-77"
    assert by_step["add-friend"].target["target_id"] == "person-12"

    # A step that ran and failed is recorded as failed, not dropped.
    assert by_step["open-app"].status == "succeeded"
    assert by_step["open-post"].status == "succeeded"
    assert by_step["add-friend"].status == "failed"
    assert by_step["add-friend"].result["error_code"] == "ELEMENT_NOT_FOUND"

    for row in rows:
        assert row.account_id == ACCOUNT
        assert row.execution_id == EXECUTION
        assert row.device_serial == "PHONE-ACTIVITY"
        assert row.platform == "instagram"
        # The operator-facing sentence travels with the row, so a timeline does
        # not have to re-derive it from a step type.
        assert row.result["summary"]


@pytest.mark.asyncio
async def test_attempt_and_transition_rows_accompany_each_action(
    tenancy_session_factory, monkeypatch
):
    await _seed(tenancy_session_factory)
    await _flush(tenancy_session_factory, _buffer_entries(monkeypatch, STEPS))

    attempts = await _read(tenancy_session_factory, select(AccountActionAttempt))
    transitions = await _read(tenancy_session_factory, select(AccountActionTransition))

    assert len(attempts) == 3
    assert {a.attempt_no for a in attempts} == {1}
    assert sorted(a.outcome for a in attempts) == ["failed", "succeeded", "succeeded"]
    # queued (written by create_action) -> running -> terminal, for each of the
    # three actions.
    assert len(transitions) == 9
    assert {t.to_status for t in transitions} == {
        "queued",
        "running",
        "succeeded",
        "failed",
    }


@pytest.mark.asyncio
async def test_replaying_the_same_scenario_does_not_duplicate_rows(
    tenancy_session_factory, monkeypatch
):
    """A Temporal retry re-runs the step; the ledger must not grow a second row.

    Idempotency rides stable_action_key = hash(org, account, execution, step_id,
    action_type, target).
    """
    await _seed(tenancy_session_factory)

    for _ in range(2):
        await _flush(tenancy_session_factory, _buffer_entries(monkeypatch, STEPS))

    rows = await _read(
        tenancy_session_factory,
        select(AccountAction).where(AccountAction.org_id == ORG),
    )
    attempts = await _read(tenancy_session_factory, select(AccountActionAttempt))

    assert len(rows) == 3, "second run must reuse the same ledger rows"
    # No action gains a second attempt. A succeeded row short-circuits in
    # _prepare_action; a failed one is terminal, so the re-claim raises inside
    # its savepoint and the batch records nothing rather than reopening a
    # closed action. Both are the pre-existing ledger contract — the flush must
    # not quietly duplicate work on a replay.
    assert len(attempts) == 3
    assert {a.attempt_no for a in attempts} == {1}
    failed_row = next(r for r in rows if r.step_id == "add-friend")
    assert failed_row.status == "failed"


@pytest.mark.asyncio
async def test_unidentified_target_is_not_filed_against_the_button(
    tenancy_session_factory, monkeypatch
):
    """A connection request that never named a person writes no row at all.

    The selector it tapped ("Add Friend") is not an identity; a row keyed on it
    would claim the account acted on someone the screen never named.
    """
    await _seed(tenancy_session_factory)
    entries = _buffer_entries(
        monkeypatch,
        [
            {
                "type": "_activity_probe",
                "id": "add-friend",
                "value": "Add Friend",
                "_fail": True,
                "semantic_action": "connection.request",
            }
        ],
    )

    assert entries == []
    rows = await _read(
        tenancy_session_factory,
        select(AccountAction).where(AccountAction.org_id == ORG),
    )
    assert rows == []
