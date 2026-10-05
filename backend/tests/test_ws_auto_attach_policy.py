from __future__ import annotations

from types import SimpleNamespace

import pytest

import web.ws as ws_module


class _AsyncSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_auto_attach_policy_allows_non_db_mode():
    assert (
        await ws_module._relay_scrcpy_auto_attach_allowed_for_serial(
            "phone-a",
            db_enabled=False,
        )
        is True
    )


@pytest.mark.asyncio
async def test_auto_attach_policy_fails_closed_when_db_check_fails(monkeypatch):
    def _broken_session():
        raise RuntimeError("db pool exhausted")

    monkeypatch.setattr(ws_module, "AsyncSessionLocal", _broken_session)

    assert (
        await ws_module._relay_scrcpy_auto_attach_allowed_for_serial(
            "phone-a",
            db_enabled=True,
        )
        is False
    )


@pytest.mark.asyncio
async def test_auto_attach_policy_fails_closed_for_unregistered_device(monkeypatch):
    async def _missing_device(db, serial):
        return None

    monkeypatch.setattr(ws_module, "AsyncSessionLocal", lambda: _AsyncSession())
    monkeypatch.setattr(ws_module, "lookup_device_by_serial", _missing_device)

    assert (
        await ws_module._relay_scrcpy_auto_attach_allowed_for_serial(
            "phone-a",
            db_enabled=True,
        )
        is False
    )


@pytest.mark.asyncio
async def test_auto_attach_policy_allows_registered_device_when_db_flag_allows(
    monkeypatch,
):
    async def _registered_device(db, serial):
        return SimpleNamespace(serial="phone-a", org_id="org-a", user_id="user-a")

    async def _allowed(db, serial):
        return True

    monkeypatch.setattr(ws_module, "AsyncSessionLocal", lambda: _AsyncSession())
    monkeypatch.setattr(ws_module, "lookup_device_by_serial", _registered_device)
    monkeypatch.setattr(
        ws_module.repo,
        "relay_scrcpy_auto_attach_allowed",
        _allowed,
    )

    assert (
        await ws_module._relay_scrcpy_auto_attach_allowed_for_serial(
            "phone-a",
            db_enabled=True,
        )
        is True
    )


@pytest.mark.asyncio
async def test_auto_attach_policy_checks_preference_with_canonical_serial(
    monkeypatch,
):
    checked: list[str] = []

    async def _registered_device(db, serial):
        return SimpleNamespace(
            serial="canonical-phone",
            org_id="org-a",
            user_id="user-a",
        )

    async def _allowed(db, serial):
        checked.append(serial)
        return False

    monkeypatch.setattr(ws_module, "AsyncSessionLocal", lambda: _AsyncSession())
    monkeypatch.setattr(ws_module, "lookup_device_by_serial", _registered_device)
    monkeypatch.setattr(
        ws_module.repo,
        "relay_scrcpy_auto_attach_allowed",
        _allowed,
    )

    assert (
        await ws_module._relay_scrcpy_auto_attach_allowed_for_serial(
            "relay-alias:5555",
            db_enabled=True,
        )
        is False
    )
    assert checked == ["canonical-phone"]
