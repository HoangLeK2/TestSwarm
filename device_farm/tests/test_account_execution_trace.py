"""account -> executions -> steps: the path a ban investigation walks.

Before the account_id filter there was no first hop at all, so the step rows
that had been recorded all along were unreachable from an account.
"""
from __future__ import annotations

import pytest

from db.crud.execution import list_executions
from db.crud.execution_steps import list_execution_steps, upsert_execution_step
from db.models.account import Account
from db.models.execution import Execution
from db.models.organization import Organization

pytest_plugins = ["tests.tenancy_test_support"]

ORG = "org-trace"
BANNED = "account-banned"
OTHER = "account-other"


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add(
            Organization(
                id=ORG,
                business_name="Trace org",
                business_email="trace@example.com",
            )
        )
        for account_id in (BANNED, OTHER):
            db.add(
                Account(
                    id=account_id,
                    org_id=ORG,
                    platform="facebook",
                    username=account_id,
                )
            )
        # Two campaign runs and one manual run for the banned account. The
        # manual run has no campaign_id on purpose: the default org-scoped
        # listing joins Campaign and would drop it.
        db.add(
            Execution(
                id="exec-campaign-1",
                org_id=ORG,
                account_id=BANNED,
                campaign_id=None,
                run_type="campaign_run",
            )
        )
        db.add(
            Execution(
                id="exec-manual",
                org_id=ORG,
                account_id=BANNED,
                campaign_id=None,
                run_type="testrun",
            )
        )
        db.add(
            Execution(
                id="exec-other",
                org_id=ORG,
                account_id=OTHER,
                campaign_id=None,
                run_type="campaign_run",
            )
        )
        await db.commit()


STEPS = [
    ("launch_app", "passed", None),
    ("tap_selector", "passed", None),
    ("input_text", "passed", None),
    ("content_interaction", "failed", "ELEMENT_NOT_FOUND"),
]


async def _seed_steps(session_factory) -> None:
    async with session_factory() as db:
        for index, (step_type, status, reason) in enumerate(STEPS):
            await upsert_execution_step(
                db,
                execution_id="exec-campaign-1",
                org_id=ORG,
                step_index=index,
                step_id=f"s{index}",
                step_type=step_type,
                status=status,
                message=f"{step_type} {status}",
                error_json={"reason_code": reason} if reason else {},
                effective_config_json={
                    "trace": {
                        "account_id": BANNED,
                        "semantic_action": step_type,
                    }
                },
            )
        await db.commit()


@pytest.mark.asyncio
async def test_account_filter_returns_every_run_including_campaignless(
    tenancy_session_factory,
):
    await _seed(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        items, total = await list_executions(
            db, org_id=ORG, account_id=BANNED, limit=50
        )

    ids = {row.id for row in items}
    assert total == 2
    # The manual run has no campaign. The Campaign join used by the default
    # org-scoped branch would have hidden it.
    assert ids == {"exec-campaign-1", "exec-manual"}
    assert "exec-other" not in ids


@pytest.mark.asyncio
async def test_steps_are_reachable_from_the_account(tenancy_session_factory):
    await _seed(tenancy_session_factory)
    await _seed_steps(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        executions, _ = await list_executions(
            db, org_id=ORG, account_id=BANNED, limit=50
        )
        walked = []
        for execution in executions:
            walked.extend(await list_execution_steps(db, execution.id))

    # Every step of the account's runs, in order, with the failure that a ban
    # investigation is looking for.
    assert [row.step_type for row in walked] == [s[0] for s in STEPS]
    failed = [row for row in walked if row.status == "failed"]
    assert len(failed) == 1
    assert failed[0].step_type == "content_interaction"
    assert failed[0].error_json["reason_code"] == "ELEMENT_NOT_FOUND"
    assert failed[0].step_index == 3
    # The step row names the account without a join, via the trace P0 seeds.
    assert failed[0].effective_config_json["trace"]["account_id"] == BANNED


@pytest.mark.asyncio
async def test_account_filter_does_not_leak_across_tenants(tenancy_session_factory):
    await _seed(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        items, total = await list_executions(
            db, org_id="org-someone-else", account_id=BANNED, limit=50
        )

    assert total == 0
    assert items == []
