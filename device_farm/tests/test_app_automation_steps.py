from __future__ import annotations

from types import SimpleNamespace

from api.schemas.scenario import ScenarioModel
from common.scenario_schema import validate_scenario
from common.variable_resolver import VariableContext
from tasks.scenario.steps.app_automation import (
    handle_assert_app_state,
    handle_fill_form,
    handle_login_if_needed,
)


_XML = """
<hierarchy>
  <node text="Username" class="android.widget.TextView" bounds="[40,100][240,150]" />
  <node text="" resource-id="com.example:id/username" class="android.widget.EditText" bounds="[260,90][900,170]" />
  <node text="Password" class="android.widget.TextView" bounds="[40,220][240,270]" />
  <node text="" resource-id="com.example:id/password" class="android.widget.EditText" bounds="[260,210][900,290]" />
  <node text="Login" class="android.widget.Button" bounds="[300,360][700,440]" />
</hierarchy>
"""


def _profile() -> dict:
    return {
        "package": "com.example.app",
        "semantic_locators": {
            "username_field": {"candidates": [{"resource_id_contains": "username"}]},
            "password_field": {"candidates": [{"resource_id_contains": "password"}]},
            "login_button": {"candidates": [{"by": "text", "value": "Login"}]},
        },
        "login_recipe": {
            "detect_logged_in": {"any_text": ["Home"]},
            "fields": {
                "username": {"locator": "username_field", "value_from": "account.username"},
                "password": {"locator": "password_field", "value_from": "secret.login_password"},
            },
            "submit": {"locator": "login_button"},
        },
        "form_recipes": {
            "basic": {
                "fields": {
                    "username": {"locator": "username_field", "value_from": "variables.username"},
                },
                "submit": {"locator": "login_button"},
            }
        },
    }


class FakeU2:
    def __init__(self) -> None:
        self.clicked: list[str] = []
        self.sent: list[str] = []
        self.cleared = 0

    def find_element_with_bounds_spec(self, spec, timeout=0.5):
        by, value = spec.primary_by_value()
        return {"eid": f"{by}:{value}", "bounds": {"left": 1, "top": 2, "right": 3, "bottom": 4}}

    def element_click(self, eid: str) -> None:
        self.clicked.append(eid)

    def clear_text(self) -> None:
        self.cleared += 1

    def send_keys(self, text: str) -> None:
        self.sent.append(text)

    def app_current(self) -> dict:
        return {"package": "com.example.app", "activity": ".MainActivity"}


class FakeDevice:
    serial = "SERIAL1"
    screen_width = 1080
    screen_height = 1920

    def __init__(self, xml: str = _XML) -> None:
        self.u2 = FakeU2()
        self._xml = xml
        self.taps: list[tuple[int, int]] = []

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return self._xml

    def ensure_u2_healthy(self) -> None:
        return None

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))


def _sc(xml: str = _XML):
    return SimpleNamespace(
        device=FakeDevice(xml),
        serial="SERIAL1",
        scenario={"app_automation_profile": _profile()},
        var_ctx=VariableContext(
            scenario_vars={"username": "form-user", "login_password": "secret-pw"},
            campaign_vars={"__ACCOUNT_USERNAME__": "account-user"},
            device_serial="SERIAL1",
        ),
        w=1080,
        h=1920,
        cancel_event=None,
        scenario_iw_config={},
    )


def test_schema_accepts_app_automation_steps():
    scenario = {
        "name": "app automation",
        "steps": [
            {"type": "login_if_needed", "profile": _profile()},
            {"type": "fill_form", "profile": _profile(), "recipe": "basic"},
            {"type": "assert_app_state", "profile": _profile(), "any_text": ["Login"]},
        ],
    }

    assert ScenarioModel.validate_dict(scenario) == []
    assert validate_scenario(scenario) == []


def test_assert_app_state_passes_with_expected_text_and_package():
    sc = _sc()
    result = {"index": 0, "type": "assert_app_state", "ok": True}

    handle_assert_app_state(
        sc,
        {"type": "assert_app_state", "any_text": ["Login"], "not_text": ["Error"]},
        0,
        result,
    )

    assert result["ok"] is True
    assert result["message"] == "assert_app_state: passed"


def test_assert_app_state_fails_for_forbidden_text():
    sc = _sc()
    result = {"index": 0, "type": "assert_app_state", "ok": True}

    handle_assert_app_state(sc, {"type": "assert_app_state", "not_text": ["Login"]}, 0, result)

    assert result["ok"] is False
    assert "forbidden text visible" in result["message"]


def test_login_if_needed_skips_when_logged_in_text_visible():
    sc = _sc("<hierarchy><node text='Home' class='android.widget.TextView' bounds='[1,1][2,2]' /></hierarchy>")
    result = {"index": 0, "type": "login_if_needed", "ok": True}

    handle_login_if_needed(sc, {"type": "login_if_needed"}, 0, result)

    assert result["ok"] is True
    assert result["login_state"] == "already_logged_in"
    assert sc.device.u2.sent == []


def test_fill_form_inputs_values_and_submits():
    sc = _sc()
    result = {"index": 0, "type": "fill_form", "ok": True}

    handle_fill_form(sc, {"type": "fill_form", "recipe": "basic"}, 0, result)

    assert result["ok"] is True
    assert sc.device.u2.sent == ["form-user"]
    assert sc.device.u2.cleared == 1
    assert any("Login" in clicked for clicked in sc.device.u2.clicked)
