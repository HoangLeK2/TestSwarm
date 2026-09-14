"""execution_events must be answerable by account, not just by execution.

The events already recorded every step at every depth; the identity that makes
them useful sat inside the JSON payload where no index could reach it. These
tests pin the promotion to columns, the fallbacks, and the migration backfill.
"""
from __future__ import annotations

import importlib

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from db.models.execution import Execution
from db.models.execution_event import ExecutionEvent
from db.models.organization import Organization
from services.execution.event_publisher import _event_identity, enqueue_execution_event

pytest_plugins = ["tests.tenancy_test_support"]

ORG = "org-events"
ACCOUNT = "account-events"
EXECUTION = "execution-events"


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add(
            Organization(
                id=ORG,
                business_name="Events org",
                business_email="events@example.com",
            )
        )
        db.add(
            Execution(
                id=EXECUTION,
                org_id=ORG,
                account_id=ACCOUNT,
                run_type="campaign_run",
                device_config={"device_serial": "PHONE-FALLBACK"},
            )
        )
        await db.commit()


STEP_PAYLOAD = {
    "step_index": 0,
    "step_id": "RVeObnJSi8",
    "step_type": "tap_selector",
    "depth": 3,
    "ok": True,
    "trace": {
        "account_id": ACCOUNT,
        "device_serial": "PHONE-FROM-TRACE",
        "step_path": "0/login.else/zON2.then/RVeObnJSi8",
        "depth": 3,
    },
}


@pytest.mark.asyncio
async def test_step_event_promotes_identity_into_columns(tenancy_session_factory):
    await _seed(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        await enqueue_execution_event(
            db,
            event_type="step.completed",
            execution_id=EXECUTION,
            organization_id=ORG,
            step_id="RVeObnJSi8",
            payload=STEP_PAYLOAD,
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        row = (
            await db.execute(select(ExecutionEvent).where(ExecutionEvent.org_id == ORG))
        ).scalar_one()

    assert row.account_id == ACCOUNT
    assert row.device_serial == "PHONE-FROM-TRACE"
    assert row.step_path == "0/login.else/zON2.then/RVeObnJSi8"
    # The payload is untouched; the columns are a projection of it.
    assert row.payload["trace"]["step_path"] == row.step_path


@pytest.mark.asyncio
async def test_lifecycle_event_falls_back_to_the_execution(tenancy_session_factory):
    """An execution.started belongs to an account even with no step trace."""
    await _seed(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        await enqueue_execution_event(
            db,
            event_type="execution.started",
            execution_id=EXECUTION,
            organization_id=ORG,
            payload={},
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        row = (
            await db.execute(select(ExecutionEvent).where(ExecutionEvent.org_id == ORG))
        ).scalar_one()

    assert row.account_id == ACCOUNT
    assert row.device_serial == "PHONE-FALLBACK"
    # No step, so no path. Inventing one would make the tree index lie.
    assert row.step_path is None


def test_identity_prefers_trace_over_execution():
    execution = Execution(
        id=EXECUTION,
        org_id=ORG,
        account_id="account-from-execution",
        run_type="campaign_run",
        device_config={"device_serial": "PHONE-FALLBACK"},
    )
    identity = _event_identity(STEP_PAYLOAD, execution)
    assert identity["account_id"] == ACCOUNT
    assert identity["device_serial"] == "PHONE-FROM-TRACE"


def test_identity_reads_evidence_when_trace_is_absent():
    execution = Execution(id=EXECUTION, org_id=ORG, run_type="campaign_run")
    identity = _event_identity(
        {"evidence": {"account_id": "acc-x", "device_serial": "PHONE-X"}},
        execution,
    )
    assert identity["account_id"] == "acc-x"
    assert identity["device_serial"] == "PHONE-X"


def test_identity_treats_blank_strings_as_missing():
    execution = Execution(
        id=EXECUTION, org_id=ORG, account_id="acc-real", run_type="campaign_run"
    )
    identity = _event_identity({"trace": {"account_id": "   "}}, execution)
    assert identity["account_id"] == "acc-real"


@pytest.mark.asyncio
async def test_account_query_is_scoped_to_its_tenant(tenancy_session_factory):
    await _seed(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        await enqueue_execution_event(
            db,
            event_type="step.completed",
            execution_id=EXECUTION,
            organization_id=ORG,
            payload=STEP_PAYLOAD,
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        leaked = (
            (
                await db.execute(
                    select(ExecutionEvent).where(
                        ExecutionEvent.org_id == "org-someone-else",
                        ExecutionEvent.account_id == ACCOUNT,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert leaked == []


@pytest.mark.asyncio
async def test_migration_adds_columns_and_indexes_on_sqlite():
    migration = importlib.import_module(
        "db.migrations.131_execution_events_account_columns"
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE execution_events ("
                    "id INTEGER PRIMARY KEY, org_id VARCHAR(36), "
                    "execution_id VARCHAR(36), payload TEXT, occurred_at TIMESTAMP)"
                )
            )
            await migration.upgrade(conn)

            columns = {
                row[1]
                for row in (
                    await conn.execute(text("PRAGMA table_info(execution_events)"))
                ).all()
            }
            indexes = {
                row[1]
                for row in (
                    await conn.execute(text("PRAGMA index_list(execution_events)"))
                ).all()
            }
        assert {"account_id", "device_serial", "step_path"} <= columns
        assert {
            "idx_execution_events_org_account_time",
            "idx_execution_events_exec_path",
        } <= indexes
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_retention_spares_the_events_an_investigation_reads(
    tenancy_session_factory,
):
    """Failures outlive successes.

    A ban surfaces weeks after the run. Under a flat 30-day purge the only
    record of what the account did was already gone — verified on real data:
    an execution from 35 days ago had 3 step rows and 0 events.
    """
    from datetime import datetime, timedelta, timezone

    from db.crud.execution_events import purge_events_older_than
    from services.execution.outbox_poller import (
        FORENSIC_EVENT_PREFIXES,
        FORENSIC_EVENT_TYPES,
    )

    await _seed(tenancy_session_factory)
    old = datetime.now(timezone.utc) - timedelta(days=90)

    async with tenancy_session_factory() as db:
        for event_type in (
            "step.completed",
            "step.started",
            "step.failed",
            "incident.detected",
            "execution.dlq.opened",
            "execution.failed",
        ):
            row = await enqueue_execution_event(
                db,
                event_type=event_type,
                execution_id=EXECUTION,
                organization_id=ORG,
                payload=STEP_PAYLOAD,
            )
            # Only published rows are eligible; backdate them past the cutoff.
            row.created_at = old
            row.published_at = old
        await db.commit()

    async with tenancy_session_factory() as db:
        await purge_events_older_than(
            db,
            cutoff=datetime.now(timezone.utc) - timedelta(days=30),
            keep_types=FORENSIC_EVENT_TYPES,
            keep_type_prefixes=FORENSIC_EVENT_PREFIXES,
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        survivors = {
            row.event_type
            for row in (
                await db.execute(select(ExecutionEvent).where(ExecutionEvent.org_id == ORG))
            )
            .scalars()
            .all()
        }

    assert survivors == {
        "step.failed",
        "incident.detected",
        "execution.dlq.opened",
        "execution.failed",
    }
    assert "step.completed" not in survivors
    assert "step.started" not in survivors


@pytest.mark.asyncio
async def test_forensic_window_is_not_forever(tenancy_session_factory):
    """Past its own longer window the forensic set goes too."""
    from datetime import datetime, timedelta, timezone

    from db.crud.execution_events import purge_events_older_than

    await _seed(tenancy_session_factory)
    ancient = datetime.now(timezone.utc) - timedelta(days=500)

    async with tenancy_session_factory() as db:
        row = await enqueue_execution_event(
            db,
            event_type="step.failed",
            execution_id=EXECUTION,
            organization_id=ORG,
            payload=STEP_PAYLOAD,
        )
        row.created_at = ancient
        row.published_at = ancient
        await db.commit()

    async with tenancy_session_factory() as db:
        deleted = await purge_events_older_than(
            db, cutoff=datetime.now(timezone.utc) - timedelta(days=365)
        )
        await db.commit()

    assert deleted == 1
