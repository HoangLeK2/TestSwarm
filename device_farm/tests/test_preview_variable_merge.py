"""Preview/run variable merge — persisted layers must beat stale client payload."""

from __future__ import annotations

import pytest

from api.routes.device_control import scenarios as preview_scenarios
from api.routes.device_control.scenarios import merge_preview_variable_layers
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
