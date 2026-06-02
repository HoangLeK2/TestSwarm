"""Legacy campaign scenario fallback for dispatch/runtime."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.campaign.scenario_sources import (
    org_scenario_refs_from_campaign,
    resolve_campaign_scenario_refs,
)


def _campaign_without_org_refs() -> MagicMock:
    campaign = MagicMock()
    campaign.id = "camp-legacy"
    campaign.__dict__["org_scenario_refs"] = []
    return campaign


@pytest.mark.asyncio
async def test_resolve_uses_legacy_scenarios_when_org_refs_empty():
    campaign = _campaign_without_org_refs()
    legacy = SimpleNamespace(
        id="sc-legacy-1",
        name="Crawl bài viết",
        steps=[{"type": "wait", "duration": 1}],
        order=0,
    )

    with patch(
        "db.crud.campaign.list_scenarios",
        new=AsyncMock(return_value=[legacy]),
    ), patch(
        "db.crud.scenario_template.list_templates",
        new=AsyncMock(return_value=[]),
    ):
        refs = await resolve_campaign_scenario_refs(AsyncMock(), campaign)

    assert len(refs) == 1
    assert refs[0]["scenario_id"] == "sc-legacy-1"
    assert refs[0]["source"] == "legacy"
    assert org_scenario_refs_from_campaign(campaign) == []


@pytest.mark.asyncio
async def test_resolve_prefers_org_library_refs():
    ref = SimpleNamespace(
        org_scenario_id="org-sc-1",
        order_index=0,
        pinned_version=2,
    )
    campaign = MagicMock()
    campaign.id = "camp-mix"
    campaign.__dict__["org_scenario_refs"] = [ref]

    with patch(
        "db.crud.campaign.list_scenarios",
        new=AsyncMock(),
    ) as list_legacy:
        refs = await resolve_campaign_scenario_refs(AsyncMock(), campaign)

    list_legacy.assert_not_awaited()
    assert len(refs) == 1
    assert refs[0]["scenario_id"] == "org-sc-1"
    assert refs[0]["scenario_version"] == 2
    assert refs[0]["source"] == "org_library"
