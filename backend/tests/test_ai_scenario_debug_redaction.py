from __future__ import annotations

import json

from runtime.ai.ai_scenario import _build_input_context_json, _write_debug_json


def test_debug_artifact_records_shape_without_raw_prompt_or_ui_secrets(
    monkeypatch,
    tmp_path,
) -> None:
    canary = "adl-secret-canary-7319"
    target = tmp_path / "scenario-debug.json"
    monkeypatch.setenv("SCENARIO_DEBUG_JSON_PATH", str(target))
    monkeypatch.setenv("DEVICE_FARM_ENV", "dev")

    _write_debug_json(
        {
            "instructions": f"Log in with password {canary}",
            "device_context": {"token": canary, "package": "com.example.app"},
            "ui_snapshots": [
                {
                    "screen": 1,
                    "description": "login",
                    "xml": f'<node password="{canary}" />',
                }
            ],
        }
    )

    raw = target.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert canary not in raw
    assert payload["instructions"]["length"] > 0
    assert payload["ui_snapshots"][0]["xml_length"] > 0
    assert payload["device_context_keys"] == ["package", "token"]


def test_llm_context_redacts_credential_fields_and_password_nodes() -> None:
    canary = "adl-secret-canary-9472"

    payload = _build_input_context_json(
        "Verify the login screen",
        ui_xml=f'<hierarchy><node password="true" text="{canary}" /></hierarchy>',
        device_context={
            "package": "com.example.app",
            "password": canary,
            "nested": {"token": canary, "screen": "login"},
        },
    )
    serialized = json.dumps(payload)

    assert canary not in serialized
    assert payload["device_context"]["package"] == "com.example.app"
    assert payload["device_context"]["password"] == "[REDACTED]"
    assert payload["device_context"]["nested"]["token"] == "[REDACTED]"
    assert "password=\"true\"" in payload["ui_snapshots"][0]["xml"]
