"""Trace pages order events by when they happened, not by when they were written.

Workflow-side telemetry ships in batches, so a batch row lands in the table well
after events that occurred later. Paging by ``ExecutionEvent.id`` put those rows
at the wrong place in the timeline, which the step-log fold reads as a step that
failed after completing, or as a loop whose iterations all share one bucket.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.crud.execution_events import insert_execution_event
from db.database import Base
from services.execution_trace import _list_execution_event_page


_T0 = datetime(2026, 9, 5, 1, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


async def _seed(db: AsyncSession, insertion_order: list[int]) -> None:
    """Insert events whose row ids ascend in ``insertion_order``, seconds apart."""
    for offset in insertion_order:
        await insert_execution_event(
            db,
            event_type="step.completed",
            organization_id="org-order",
            execution_id="exec-order",
            event_id=f"evt-{offset}",
            occurred_at=_T0 + timedelta(seconds=offset),
            payload={"step_index": offset},
        )
    await db.commit()


@pytest.mark.asyncio
async def test_page_is_ordered_by_occurred_at_not_insertion_id(session_factory):
    async with session_factory() as db:
        # The batch (2, 3) is written after the later single event (4).
        await _seed(db, [0, 1, 4, 2, 3])

        rows, has_more = await _list_execution_event_page(
            db,
            "exec-order",
            since_event_id=None,
            page_size=10,
        )

    assert has_more is False
    assert [row.event_id for row in rows] == [
        "evt-0",
        "evt-1",
        "evt-2",
        "evt-3",
        "evt-4",
    ]


@pytest.mark.asyncio
async def test_paging_by_last_event_id_skips_nothing_and_repeats_nothing(
    session_factory,
):
    async with session_factory() as db:
        await _seed(db, [0, 1, 4, 2, 3])

        # No cursor: the bounded window is the NEWEST page, oldest-first inside.
        first, first_has_more = await _list_execution_event_page(
            db,
            "exec-order",
            since_event_id=None,
            page_size=2,
        )

        # With a cursor the reader walks FORWARD. Start from the oldest event
        # and page through everything after it.
        seen: list[str] = ["evt-0"]
        has_more = True
        while has_more:
            page, has_more = await _list_execution_event_page(
                db,
                "exec-order",
                since_event_id=seen[-1],
                page_size=2,
            )
            if not page:
                break
            seen.extend(row.event_id for row in page)

    assert first_has_more is True
    assert [row.event_id for row in first] == ["evt-3", "evt-4"]
    # Nothing skipped, nothing repeated, and the late batch is in timeline order.
    assert seen == ["evt-0", "evt-1", "evt-2", "evt-3", "evt-4"]
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
async def test_cursor_page_walks_forward_over_a_late_batch(session_factory):
    async with session_factory() as db:
        await _seed(db, [0, 1, 4, 2, 3])

        head, _ = await _list_execution_event_page(
            db,
            "exec-order",
            since_event_id=None,
            page_size=1,
        )
        assert [row.event_id for row in head] == ["evt-4"]

        # Live tailing anchors on evt-0 (the first thing the UI saw); the late
        # batch must still come back in timeline order behind it.
        tail, has_more = await _list_execution_event_page(
            db,
            "exec-order",
            since_event_id="evt-0",
            page_size=10,
        )

    assert has_more is False
    assert [row.event_id for row in tail] == ["evt-1", "evt-2", "evt-3", "evt-4"]


@pytest.mark.asyncio
async def test_same_timestamp_falls_back_to_insertion_id(session_factory):
    async with session_factory() as db:
        for suffix in ("a", "b", "c"):
            await insert_execution_event(
                db,
                event_type="step.completed",
                organization_id="org-order",
                execution_id="exec-order",
                event_id=f"evt-{suffix}",
                occurred_at=_T0,
                payload={},
            )
        await db.commit()

        rows, _ = await _list_execution_event_page(
            db,
            "exec-order",
            since_event_id="evt-a",
            page_size=10,
        )

    assert [row.event_id for row in rows] == ["evt-b", "evt-c"]
