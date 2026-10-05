"""Regression tests for campaign aggregation scheduling."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_evaluate_now_uses_loop_scoped_activity_session(monkeypatch):
    from db import database
    from services.campaign import aggregator, aggregator_scheduler

    fake_db = object()
    evaluated: list[dict[str, Any]] = []

    @asynccontextmanager
    async def fake_activity_session():
        yield fake_db

    def unexpected_main_session():
        raise AssertionError("campaign aggregation must not use AsyncSessionLocal")

    async def fake_evaluate_campaign_status(db, **kwargs):
        assert db is fake_db
        evaluated.append(kwargs)

    monkeypatch.setattr(database, "activity_session", fake_activity_session)
    monkeypatch.setattr(database, "AsyncSessionLocal", unexpected_main_session)
    monkeypatch.setattr(
        aggregator,
        "evaluate_campaign_status",
        fake_evaluate_campaign_status,
    )

    await aggregator_scheduler._evaluate_now(
        org_id="org-1",
        campaign_id="campaign-1",
        user_id="user-1",
        reason="test",
    )

    assert evaluated == [
        {
            "org_id": "org-1",
            "campaign_id": "campaign-1",
            "user_id": "user-1",
            "reason": "test",
        }
    ]
