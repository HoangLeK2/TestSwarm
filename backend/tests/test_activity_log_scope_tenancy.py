"""activity_log_scope must not require current_org_id when user has default org."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from api.org_scope import activity_log_scope
from db.models.device import Device
from db.models.user import User
from tenancy.context import get_current_org_id
from tenancy.sqlalchemy import init_tenant_scoping


@pytest.mark.asyncio
async def test_activity_log_scope_without_current_org_id(monkeypatch) -> None:
    monkeypatch.setenv("TENANCY_STRICT_MODE", "true")
    init_tenant_scoping._installed = False  # type: ignore[attr-defined]
    init_tenant_scoping()

    user = User(
        id="user-1",
        email="u@example.com",
        name="U",
        hashed_password="x",
        default_org_id="org-1",
    )
    assert get_current_org_id() is None
    assert user.org_id == "org-1"

    executed: list[object] = []

    class _FakeResult:
        def all(self):
            return []

    async def _fake_execute(stmt, params=None):
        executed.append(stmt)
        return _FakeResult()

    db = AsyncMock()
    db.execute = _fake_execute

    with patch("api.org_scope.repo.list_organization_members", AsyncMock(return_value=[])):
        scope = await activity_log_scope(db, user)

    assert scope is not None
    assert len(executed) == 1
    stmt = executed[0]
    assert "devices" in str(stmt).lower()
    assert Device not in getattr(stmt, "_raw_columns", ())


@pytest.mark.asyncio
async def test_orm_device_select_still_strict_without_context(monkeypatch) -> None:
    monkeypatch.setenv("TENANCY_STRICT_MODE", "true")
    init_tenant_scoping._installed = False  # type: ignore[attr-defined]
    init_tenant_scoping()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from db.database import Base

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    async with factory() as session:
        with pytest.raises(RuntimeError, match="TENANCY_STRICT_MODE"):
            await session.execute(select(Device).limit(1))

    await eng.dispose()
