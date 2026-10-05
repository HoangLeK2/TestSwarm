"""Execution org-scoped access (multi-tenancy)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.execution_access import get_execution_for_user


@pytest.mark.asyncio
async def test_execution_visible_via_campaign_org():
    db = AsyncMock()
    user = SimpleNamespace(id="user-a", org_id="org-a")
    ex = SimpleNamespace(id="ex-1", campaign_id="camp-1", user_id="other-user")
    campaign = SimpleNamespace(id="camp-1", org_id="org-a")

    with patch("api.execution_access.get_execution", AsyncMock(return_value=ex)):
        with patch("api.execution_access.get_campaign", AsyncMock(return_value=campaign)):
            result = await get_execution_for_user(db, "ex-1", user)
    assert result.id == "ex-1"


@pytest.mark.asyncio
async def test_execution_cross_org_returns_404():
    db = AsyncMock()
    user = SimpleNamespace(id="user-a", org_id="org-a")
    ex = SimpleNamespace(id="ex-1", campaign_id="camp-b", user_id="user-b")
    campaign = SimpleNamespace(id="camp-b", org_id="org-b")

    with patch("api.execution_access.get_execution", AsyncMock(return_value=ex)):
        with patch("api.execution_access.get_campaign", AsyncMock(return_value=campaign)):
            with pytest.raises(HTTPException) as err:
                await get_execution_for_user(db, "ex-1", user)
    assert err.value.status_code == 404
