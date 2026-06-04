"""WS device allowlist uses default_org_id (migration 081), not dropped users.org_id."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tenancy.background import list_device_serials_for_user


@pytest.mark.asyncio
async def test_list_device_serials_uses_default_org_id_column():
    db = AsyncMock()
    user_result = MagicMock()
    user_result.first.return_value = ("org-abc", "system")
    device_result = MagicMock()
    device_result.fetchall.return_value = [("SN001",), ("SN002",)]
    db.execute = AsyncMock(side_effect=[user_result, device_result])

    serials = await list_device_serials_for_user(db, "user-1", org_id="org-xyz")

    assert serials == {"SN001", "SN002"}
    user_sql = db.execute.call_args_list[0][0][0].text
    assert "default_org_id" in user_sql
    assert "org_id" not in user_sql.split("FROM users")[1].split("WHERE")[0]
    device_params = db.execute.call_args_list[1][0][1]
    assert device_params["org_id"] == "org-xyz"


@pytest.mark.asyncio
async def test_list_device_serials_superadmin_sees_all():
    db = AsyncMock()
    user_result = MagicMock()
    user_result.first.return_value = (None, "superadmin")
    device_result = MagicMock()
    device_result.fetchall.return_value = [("SN9",)]
    db.execute = AsyncMock(side_effect=[user_result, device_result])

    serials = await list_device_serials_for_user(db, "admin-1")

    assert serials == {"SN9"}
    device_sql = db.execute.call_args_list[1][0][0].text
    assert "WHERE org_id" not in device_sql
