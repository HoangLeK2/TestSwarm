from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from api.schemas.scenario import ScenarioModel
from common.scenario_schema import validate_scenario
from common.variable_resolver import VariableContext
from db.seeds.scenario_templates import _FB_LOGIN_PROFILE_NATIVE
import tasks.scenario.steps.app_automation as app_automation_steps
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

_XML_WITH_AUTH_CODE = """
<hierarchy>
  <node text="Username" class="android.widget.TextView" bounds="[40,100][240,150]" />
  <node text="" resource-id="com.example:id/username" class="android.widget.EditText" bounds="[260,90][900,170]" />
  <node text="Password" class="android.widget.TextView" bounds="[40,220][240,270]" />
  <node text="" resource-id="com.example:id/password" class="android.widget.EditText" bounds="[260,210][900,290]" />
  <node text="Login" class="android.widget.Button" bounds="[300,360][700,440]" />
  <node text="Authentication code" class="android.widget.TextView" bounds="[40,500][340,550]" />
  <node text="" resource-id="com.example:id/approvals_code" class="android.widget.EditText" bounds="[260,490][900,570]" />
  <node text="Continue" class="android.widget.Button" bounds="[300,640][700,720]" />
</hierarchy>
"""

_XML_WAITING_FOR_APPROVAL = """
<hierarchy>
  <node text="Kiểm tra thông báo trên thiết bị khác" class="android.widget.TextView" bounds="[56,405][1204,635]" />
  <node text="Đang chờ phê duyệt" class="android.widget.TextView" bounds="[210,1626][701,1700]" />
  <node text="Thử cách khác" class="android.widget.Button" bounds="[456,2014][805,2088]" />
</hierarchy>
"""

_XML_CONFIRM_METHODS = """
<hierarchy>
  <node text="Chọn một cách để xác nhận đó là bạn" class="android.widget.TextView" bounds="[56,315][1204,545]" />
  <node text="Ứng dụng xác thực" class="android.widget.TextView" bounds="[238,1120][702,1194]" />
  <node text="Tiếp tục" class="android.widget.Button" bounds="[531,2630][730,2704]" />
</hierarchy>
"""

_XML_WITH_FACEBOOK_AUTH_CODE = """
<hierarchy>
  <node text="Đi đến ứng dụng xác thực" class="android.widget.TextView" bounds="[56,405][1204,527]" />
  <node text="" content-desc="Mã," class="android.widget.EditText" bounds="[112,1560][1022,1632]" />
  <node text="Tiếp tục" class="android.widget.Button" bounds="[531,1933][730,2007]" />
</hierarchy>
"""

_XML_FACEBOOK_LOGIN_EN = """
<hierarchy>
  <node content-desc="Mobile number or email," class="android.widget.EditText" bounds="[48,343][438,373]" />
  <node content-desc="Password," class="android.widget.EditText" bounds="[48,451][438,481]" />
  <node content-desc="Log in" class="android.widget.Button" bounds="[24,517][516,583]" />
  <node text="Log in" content-desc="Log in" class="android.view.View" bounds="[239,534][302,567]" />
</hierarchy>
"""

_XML_WAITING_FOR_APPROVAL_EN = """
<hierarchy>
  <node text="Check your notifications on another device" class="android.view.View" bounds="[24,245][516,351]" />
  <node text="Waiting for approval" class="android.view.View" bounds="[90,795][297,828]" />
  <node text="Try another way" content-desc="Try another way" class="android.view.View" bounds="[188,959][352,992]" />
</hierarchy>
"""

_XML_CONFIRM_METHODS_EN = """
<hierarchy>
  <node text="Choose a way to confirm it’s you" class="android.view.View" bounds="[24,206][516,306]" />
  <node text="Authentication app" content-desc="Authentication app" class="android.view.View" bounds="[102,560][300,593]" />
  <node text="Continue" content-desc="Continue" class="android.view.View" bounds="[223,1091][317,1124]" />
</hierarchy>
"""

_XML_WITH_FACEBOOK_AUTH_CODE_EN = """
<hierarchy>
  <node text="Enter code" class="android.view.View" bounds="[24,206][516,306]" />
  <node content-desc="Code," class="android.widget.EditText" bounds="[48,451][438,481]" />
  <node text="Continue" content-desc="Continue" class="android.view.View" bounds="[223,1091][317,1124]" />
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


def _account_profile() -> dict:
    profile = _profile()
    profile["login_recipe"]["fields"]["password"]["value_from"] = "account.password"
    return profile


def _auth_code_profile() -> dict:
    profile = _account_profile()
    profile["semantic_locators"]["auth_code_field"] = {
        "candidates": [{"resource_id_contains": "approvals_code"}]
    }
    profile["login_recipe"]["post_submit_fields"] = {
        "auth_code": {
            "locator": "auth_code_field",
            "value_from": "account.totp_code",
            "required": False,
        }
    }
    profile["login_recipe"]["post_submit"] = {"tap_text_any": ["Continue"]}
    return profile


def _facebook_auth_code_profile() -> dict:
    profile = _account_profile()
    profile["semantic_locators"]["auth_code_field"] = {
        "candidates": [{"by": "description", "value": "Mã,"}]
    }
    profile["login_recipe"]["post_submit_actions"] = [
        {
            "when_text_any": ["Kiểm tra thông báo trên thiết bị khác", "Đang chờ phê duyệt"],
            "tap_text_any": ["Thử cách khác"],
            "timeout_s": 0,
            "wait_after_s": 0,
        },
        {
            "when_text_any": ["Chọn một cách để xác nhận đó là bạn", "Ứng dụng xác thực"],
            "tap_text_any": ["Ứng dụng xác thực"],
            "timeout_s": 0,
            "wait_after_s": 0,
        },
        {
            "when_text_any": ["Chọn một cách để xác nhận đó là bạn", "Ứng dụng xác thực"],
            "tap_text_any": ["Tiếp tục"],
            "timeout_s": 0,
            "wait_after_s": 0,
        },
    ]
    profile["login_recipe"]["post_submit_fields"] = {
        "auth_code": {
            "locator": "auth_code_field",
            "value_from": "account.totp_code",
            "required": False,
        }
    }
    profile["login_recipe"]["post_submit"] = {"tap_text_any": ["Tiếp tục"]}
    return profile


class FakeU2:
    def __init__(self, device=None) -> None:
        self.device = device
        self.clicked: list[str] = []
        self.sent: list[str] = []
        self.cleared = 0

    def find_element_with_bounds_spec(self, spec, timeout=0.5):
        by, value = spec.primary_by_value()
        xml = self.device.hierarchy_xml() if self.device is not None else ""
        if by == "text" and f'text="{value}"' not in xml:
            return None
        if by in {"description", "content-desc"} and f'content-desc="{value}"' not in xml:
            return None
        if by == "resource-id" and f'resource-id="{value}"' not in xml:
            return None
        return {"eid": f"{by}:{value}", "bounds": {"left": 1, "top": 2, "right": 3, "bottom": 4}}

    def element_click(self, eid: str) -> None:
        self.clicked.append(eid)
        if self.device is not None:
            self.device.advance_on_click(eid)

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

    def __init__(self, xml: str | list[str] = _XML) -> None:
        self._xmls = xml if isinstance(xml, list) else [xml]
        self._xml_idx = 0
        self.u2 = FakeU2(self)
        self.taps: list[tuple[int, int]] = []

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return self._xmls[self._xml_idx]

    def advance_on_click(self, eid: str) -> None:
        transition_labels = (
            "Login",
            "Log in",
            "Thử cách khác",
            "Try another way",
            "Ứng dụng xác thực",
            "Authentication app",
            "Tiếp tục",
            "Continue",
        )
        if any(label in eid for label in transition_labels) and self._xml_idx < len(self._xmls) - 1:
            self._xml_idx += 1

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
            campaign_vars={
                "__ACCOUNT_USERNAME__": "account-user",
                "__ACCOUNT_PASSWORD__": "account-pw",
                "__ACCOUNT_TOTP_CODE__": "123456",
            },
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


def test_login_if_needed_inputs_account_password_source():
    sc = _sc()
    sc.scenario = {"app_automation_profile": _account_profile()}
    result = {"index": 0, "type": "login_if_needed", "ok": True}

    handle_login_if_needed(sc, {"type": "login_if_needed"}, 0, result)

    assert result["ok"] is True
    assert sc.device.u2.sent == ["account-user", "account-pw"]


def test_login_if_needed_supports_legacy_secret_login_password_alias():
    sc = _sc()
    sc.var_ctx = VariableContext(
        scenario_vars={},
        campaign_vars={
            "__ACCOUNT_USERNAME__": "account-user",
            "__ACCOUNT_PASSWORD__": "account-pw",
        },
        device_serial="SERIAL1",
    )
    result = {"index": 0, "type": "login_if_needed", "ok": True}

    handle_login_if_needed(sc, {"type": "login_if_needed"}, 0, result)

    assert result["ok"] is True
    assert sc.device.u2.sent == ["account-user", "account-pw"]


def test_login_if_needed_fills_optional_post_submit_auth_code_when_visible():
    sc = _sc(_XML_WITH_AUTH_CODE)
    sc.scenario = {"app_automation_profile": _auth_code_profile()}
    result = {"index": 0, "type": "login_if_needed", "ok": True}

    handle_login_if_needed(sc, {"type": "login_if_needed"}, 0, result)

    assert result["ok"] is True
    assert sc.device.u2.sent == ["account-user", "account-pw", "123456"]
    assert result["post_submit_locator_trace"]["auth_code"]["matched"] is True
    assert any("Continue" in clicked for clicked in sc.device.u2.clicked)


def test_login_if_needed_generates_totp_from_activity_local_secret(monkeypatch):
    monkeypatch.setattr(app_automation_steps, "generate_totp", lambda secret: f"totp-{secret}")
    sc = _sc(_XML_WITH_AUTH_CODE)
    sc.var_ctx = VariableContext(
        scenario_vars={"__ACCOUNT_PASSWORD__": "account-pw", "__ACCOUNT_TOTP_SECRET__": "SECRET1"},
        campaign_vars={
            "__ACCOUNT_USERNAME__": "account-user",
            "__ACCOUNT_TOTP_CODE__": "stale-code",
        },
        device_serial="SERIAL1",
    )
    sc.scenario = {"app_automation_profile": _auth_code_profile()}
    result = {"index": 0, "type": "login_if_needed", "ok": True}

    handle_login_if_needed(sc, {"type": "login_if_needed"}, 0, result)

    assert result["ok"] is True
    assert sc.device.u2.sent == ["account-user", "account-pw", "totp-SECRET1"]


def test_login_if_needed_navigates_facebook_approval_before_totp():
    sc = _sc([
        _XML,
        _XML_WAITING_FOR_APPROVAL,
        _XML_CONFIRM_METHODS,
        _XML_CONFIRM_METHODS,
        _XML_WITH_FACEBOOK_AUTH_CODE,
    ])
    sc.scenario = {"app_automation_profile": _facebook_auth_code_profile()}
    result = {"index": 0, "type": "login_if_needed", "ok": True}

    handle_login_if_needed(sc, {"type": "login_if_needed"}, 0, result)

    assert result["ok"] is True
    assert sc.device.u2.sent == ["account-user", "account-pw", "123456"]
    assert [trace["executed"] for trace in result["post_submit_action_trace"]] == [True, True, True]
    assert any("Thử cách khác" in clicked for clicked in sc.device.u2.clicked)
    assert any("Ứng dụng xác thực" in clicked for clicked in sc.device.u2.clicked)
    assert result["post_submit_locator_trace"]["auth_code"]["matched"] is True


def test_builtin_facebook_login_supports_english_form_and_totp_path():
    sc = _sc([
        _XML_FACEBOOK_LOGIN_EN,
        _XML_WAITING_FOR_APPROVAL_EN,
        _XML_CONFIRM_METHODS_EN,
        _XML_CONFIRM_METHODS_EN,
        _XML_WITH_FACEBOOK_AUTH_CODE_EN,
    ])
    sc.scenario = {"app_automation_profile": deepcopy(_FB_LOGIN_PROFILE_NATIVE)}
    result = {"index": 0, "type": "login_if_needed", "ok": True}

    handle_login_if_needed(
        sc,
        {"type": "login_if_needed", "implicit_wait": {"timeout": 0.1, "poll": 0.01}},
        0,
        result,
    )

    assert result["ok"] is True
    assert sc.device.u2.sent == ["account-user", "account-pw", "123456"]
    assert [trace["executed"] for trace in result["post_submit_action_trace"]] == [True, True, True]
    assert any("Log in" in clicked for clicked in sc.device.u2.clicked)
    assert any("Try another way" in clicked for clicked in sc.device.u2.clicked)
    assert any("Authentication app" in clicked for clicked in sc.device.u2.clicked)
    assert result["post_submit_locator_trace"]["auth_code"]["matched"] is True


def test_fill_form_inputs_values_and_submits():
    sc = _sc()
    result = {"index": 0, "type": "fill_form", "ok": True}

    handle_fill_form(sc, {"type": "fill_form", "recipe": "basic"}, 0, result)

    assert result["ok"] is True
    assert sc.device.u2.sent == ["form-user"]
    assert sc.device.u2.cleared == 1
    assert any("Login" in clicked for clicked in sc.device.u2.clicked)
