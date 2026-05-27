"""Preview/run variable merge — persisted layers must beat stale client payload."""

from __future__ import annotations

from api.routes.device_control.scenarios import merge_preview_variable_layers


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
