"""Preview/run variable merge — persisted layers must beat stale client payload."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.routes.device_control import scenarios as preview_scenarios
from api.routes.device_control.scenarios import merge_preview_variable_layers, _preview_account_vars
from api.schemas.device_control import ScenarioPreviewRequest


def test_persisted_scenario_vars_override_stale_client():
    merged = merge_preview_variable_layers(
        client_vars={"GROUP_NAME": "stale-from-fe"},
        campaign_vars={"__PLATFORM__": "facebook"},
        scenario_vars={"GROUP_NAME": "fresh-from-db"},
        device_vars={},
        account_vars={},
    )
    assert merged["GROUP_NAME"] == "fresh-from-db"
    assert merged["__PLATFORM__"] == "facebook"


def test_device_and_account_vars_win_over_scenario():
    merged = merge_preview_variable_layers(
        client_vars={"GROUP_NAME": "stale"},
        campaign_vars={},
        scenario_vars={"GROUP_NAME": "global"},
        device_vars={"GROUP_NAME": "device-a"},
        account_vars={"__ACCOUNT_USERNAME__": "user1"},
    )
    assert merged["GROUP_NAME"] == "device-a"
    assert merged["__ACCOUNT_USERNAME__"] == "user1"


def test_preview_account_vars_include_totp_metadata_without_logging_secret():
    account = SimpleNamespace(
        id="account-1",
        username="user1",
        display_name="User One",
        platform="facebook",
        password_encrypted="encrypted",
        account_metadata={
            "email": "user@example.test",
            "totp_secret": "JBSWY3DPEHPK3PXP",
        },
    )

    vars_ = _preview_account_vars(account, lambda encrypted: f"pw:{encrypted}")

    assert vars_["__ACCOUNT_PASSWORD__"] == "pw:encrypted"
    assert vars_["__ACCOUNT_EMAIL__"] == "user@example.test"
    assert vars_["__ACCOUNT_TOTP_SECRET__"] == "JBSWY3DPEHPK3PXP"


@pytest.mark.asyncio
async def test_preview_uses_primary_device_account_without_explicit_binding(
    monkeypatch,
) -> None:
    async def resolve_device_vars(*args, **kwargs):
        return {}

    async def resolve_primary(*args, **kwargs):
        return {
            "__ACCOUNT_ID__": "primary-account",
            "__ACCOUNT_USERNAME__": "primary-user",
            "__ACCOUNT_PASSWORD__": "primary-password",
            "__ACCOUNT_PLATFORM__": "facebook",
        }

    monkeypatch.setattr(
        preview_scenarios,
        "_resolve_device_runtime_vars",
        resolve_device_vars,
    )
    monkeypatch.setattr(
        preview_scenarios,
        "_resolve_primary_device_account_vars",
        resolve_primary,
        raising=False,
    )
    body = ScenarioPreviewRequest(steps=[{"type": "login_if_needed"}])

    await preview_scenarios._apply_preview_variables(body, "SERIAL1", "user-1")

    assert body.variables["__ACCOUNT_ID__"] == "primary-account"
    assert body.variables["__ACCOUNT_PASSWORD__"] == "primary-password"


@pytest.mark.asyncio
async def test_preview_account_group_wins_over_primary_device_account(
    monkeypatch,
) -> None:
    async def resolve_device_vars(*args, **kwargs):
        return {}

    async def resolve_group(*args, **kwargs):
        return {"__ACCOUNT_ID__": "group-account"}

    async def unexpected_primary(*args, **kwargs):
        raise AssertionError("primary fallback must not run for an explicit group")

    monkeypatch.setattr(
        preview_scenarios,
        "_resolve_device_runtime_vars",
        resolve_device_vars,
    )
    monkeypatch.setattr(
        preview_scenarios,
        "_resolve_account_group_vars",
        resolve_group,
    )
    monkeypatch.setattr(
        preview_scenarios,
        "_resolve_primary_device_account_vars",
        unexpected_primary,
        raising=False,
    )
    body = ScenarioPreviewRequest(
        steps=[{"type": "login_if_needed"}],
        account_group_id="group-1",
    )

    await preview_scenarios._apply_preview_variables(body, "SERIAL1", "user-1")

    assert body.variables["__ACCOUNT_ID__"] == "group-account"


@pytest.mark.asyncio
async def test_explicit_account_id_resolves_that_account_not_the_device_primary(
    monkeypatch,
) -> None:
    """The account console names the account; the device's primary must not win.

    Before this branch existed the caller got no credentials at all, so a login
    run for a non-primary account submitted an empty password. Falling back to
    the primary would be worse: the run would sign the phone into a different
    account than the row the operator clicked.
    """

    async def resolve_device_vars(*args, **kwargs):
        return {}

    async def resolve_linked(serial, account_id):
        assert account_id == "picked-account"
        return {
            "__ACCOUNT_ID__": account_id,
            "__ACCOUNT_USERNAME__": "picked-user",
            "__ACCOUNT_PASSWORD__": "picked-password",
        }

    async def unexpected_primary(*args, **kwargs):
        raise AssertionError("primary fallback must not run for a named account")

    monkeypatch.setattr(
        preview_scenarios, "_resolve_device_runtime_vars", resolve_device_vars
    )
    monkeypatch.setattr(
        preview_scenarios, "_resolve_linked_account_vars", resolve_linked
    )
    monkeypatch.setattr(
        preview_scenarios,
        "_resolve_primary_device_account_vars",
        unexpected_primary,
        raising=False,
    )
    body = ScenarioPreviewRequest(
        steps=[{"type": "login_if_needed"}],
        variables={"__ACCOUNT_ID__": "picked-account"},
    )

    await preview_scenarios._apply_preview_variables(body, "SERIAL1", "user-1")

    assert body.variables["__ACCOUNT_ID__"] == "picked-account"
    assert body.variables["__ACCOUNT_PASSWORD__"] == "picked-password"


@pytest.mark.asyncio
async def test_linked_account_vars_refuse_an_account_not_attached_to_the_device(
    monkeypatch,
) -> None:
    """No link, no credentials — a login belongs to the phone it was attached to.

    The device deliberately belongs to a different user in the same org: the
    account console is org-wide, and tenant scoping (Device and Account are both
    TenantScopedModel) is what draws the boundary here, not device ownership.
    """
    import db.crud.account as account_crud
    import db.crud.device as device_crud

    device = SimpleNamespace(id="device-1", user_id="a-teammate")

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    async def get_device_by_serial(db, serial):
        return device

    async def list_device_accounts(db, device_id):
        assert device_id == "device-1"
        return [
            SimpleNamespace(
                account_id="other-account",
                account=SimpleNamespace(
                    id="other-account",
                    username="other",
                    display_name="",
                    platform="facebook",
                    password_encrypted="encrypted",
                    account_metadata={},
                ),
            )
        ]

    monkeypatch.setattr(preview_scenarios, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(device_crud, "get_device_by_serial", get_device_by_serial)
    monkeypatch.setattr(account_crud, "list_device_accounts", list_device_accounts)

    refused = await preview_scenarios._resolve_linked_account_vars(
        "SERIAL1", "unlinked-account"
    )
    assert refused == {}

    allowed = await preview_scenarios._resolve_linked_account_vars(
        "SERIAL1", "other-account"
    )
    assert allowed["__ACCOUNT_ID__"] == "other-account"
    assert allowed["__ACCOUNT_PASSWORD__"]
