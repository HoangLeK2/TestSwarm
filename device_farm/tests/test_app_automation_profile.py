from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.app_automation_profile import (
    redacted_profile_dump,
    validate_app_automation_profile,
    watcher_effective_package,
)


def _minimal_profile() -> dict:
    return {
        "package": "com.example.app",
        "semantic_locators": {
            "username_field": {
                "candidates": [
                    {"resource_id_contains": "username"},
                    {"text_near": ["Username"], "target_class": "android.widget.EditText"},
                ],
            },
            "password_field": {
                "candidates": [
                    {"resource_id_contains": "password"},
                    {"text_near": ["Password"], "target_class": "android.widget.EditText"},
                ],
            },
            "login_button": {
                "candidates": [
                    {"by": "text", "value": "Login"},
                ],
            },
        },
    }


def test_validates_minimal_profile_contract():
    profile = validate_app_automation_profile(_minimal_profile())

    assert profile.package == "com.example.app"
    assert profile.profile_version == 1
    assert profile.entry_state.launch is True
    assert set(profile.semantic_locators) == {"username_field", "password_field", "login_button"}


def test_login_recipe_uses_references_not_inline_secrets():
    raw = _minimal_profile()
    raw["login_recipe"] = {
        "detect_logged_in": {"any_text": ["Home"]},
        "fields": {
            "username": {"locator": "username_field", "value_from": "account.username"},
            "password": {"locator": "password_field", "value_from": "secret.login_password"},
        },
        "submit": {"locator": "login_button"},
    }

    profile = validate_app_automation_profile(raw)
    dumped = redacted_profile_dump(profile)

    assert dumped["login_recipe"]["fields"]["password"]["value_from"] == "secret.login_password"


def test_login_recipe_accepts_optional_post_submit_auth_code():
    raw = _minimal_profile()
    raw["semantic_locators"]["auth_code_field"] = {
        "candidates": [{"resource_id_contains": "approvals_code"}]
    }
    raw["login_recipe"] = {
        "detect_logged_in": {"any_text": ["Home"]},
        "fields": {
            "username": {"locator": "username_field", "value_from": "account.username"},
            "password": {"locator": "password_field", "value_from": "account.password"},
        },
        "submit": {"locator": "login_button"},
        "post_submit_actions": [
            {
                "when_text_any": ["Check notifications on another device"],
                "tap_text_any": ["Try another way"],
                "timeout_s": 8,
            },
            {
                "when_text_any": ["Choose a way to confirm"],
                "tap_text_any": ["Authentication app"],
            },
        ],
        "post_submit_fields": {
            "auth_code": {
                "locator": "auth_code_field",
                "value_from": "account.totp_code",
                "required": False,
            }
        },
        "post_submit": {"tap_text_any": ["Continue"]},
    }

    profile = validate_app_automation_profile(raw)

    assert profile.login_recipe is not None
    assert profile.login_recipe.post_submit_actions[0].timeout_s == 8
    assert profile.login_recipe.post_submit_fields["auth_code"].required is False


def test_login_recipe_rejects_unknown_post_submit_action_locator():
    raw = _minimal_profile()
    raw["login_recipe"] = {
        "detect_logged_in": {"any_text": ["Home"]},
        "fields": {
            "username": {"locator": "username_field", "value_from": "account.username"},
            "password": {"locator": "password_field", "value_from": "account.password"},
        },
        "submit": {"locator": "login_button"},
        "post_submit_actions": [{"locator": "missing_button"}],
    }

    with pytest.raises(ValidationError, match="post-submit action"):
        validate_app_automation_profile(raw)


def test_rejects_inline_login_secret_value():
    raw = _minimal_profile()
    raw["login_recipe"] = {
        "detect_logged_in": {"any_text": ["Home"]},
        "fields": {
            "password": {"locator": "password_field", "value_from": "plain-password"},
        },
        "submit": {"locator": "login_button"},
    }

    with pytest.raises(ValidationError, match="value_from must reference"):
        validate_app_automation_profile(raw)


def test_rejects_unknown_locator_reference():
    raw = _minimal_profile()
    raw["form_recipes"] = {
        "checkout": {
            "fields": {
                "phone": {"locator": "phone_field", "value_from": "account.phone"},
            },
        },
    }

    with pytest.raises(ValidationError, match="unknown locator"):
        validate_app_automation_profile(raw)


def test_popup_watcher_inherits_profile_package_scope():
    raw = _minimal_profile()
    raw["popup_watchers"] = [
        {
            "name": "close_update_dialog",
            "when": {"text_contains": ["Update"]},
            "action": {"tap_text_any": ["Later", "Not now"]},
        }
    ]

    profile = validate_app_automation_profile(raw)

    assert watcher_effective_package(profile, profile.popup_watchers[0]) == "com.example.app"


def test_rejects_popup_watcher_without_condition():
    raw = _minimal_profile()
    raw["popup_watchers"] = [
        {
            "name": "bad_watcher",
            "when": {},
            "action": {"tap_text": "Later"},
        }
    ]

    with pytest.raises(ValidationError, match="condition must include"):
        validate_app_automation_profile(raw)


def test_rejects_dangerous_popup_action_by_default():
    raw = _minimal_profile()
    raw["popup_watchers"] = [
        {
            "name": "dangerous",
            "when": {"text_contains": ["Offer"]},
            "action": {"tap_text": "Pay now"},
        }
    ]

    with pytest.raises(ValidationError, match="unsafe watcher action"):
        validate_app_automation_profile(raw)


def test_allows_dangerous_popup_action_only_when_explicit():
    raw = _minimal_profile()
    raw["popup_watchers"] = [
        {
            "name": "explicit_purchase_test",
            "when": {"text_contains": ["Test purchase"]},
            "action": {"tap_text": "Pay now", "allow_unsafe": True},
            "scope": {"package": "com.example.sandbox"},
        }
    ]

    profile = validate_app_automation_profile(raw)

    assert watcher_effective_package(profile, profile.popup_watchers[0]) == "com.example.sandbox"


def test_locator_candidate_requires_real_signal():
    raw = _minimal_profile()
    raw["semantic_locators"]["empty"] = {"candidates": [{"tap_offset": [10, 20]}]}

    with pytest.raises(ValidationError, match="at least one selector signal"):
        validate_app_automation_profile(raw)


def test_rejects_partial_by_value_locator_candidate():
    raw = _minimal_profile()
    raw["semantic_locators"]["partial"] = {"candidates": [{"by": "text"}]}

    with pytest.raises(ValidationError, match="by and value together"):
        validate_app_automation_profile(raw)


def test_rejects_target_class_without_text_near():
    raw = _minimal_profile()
    raw["semantic_locators"]["bad_target"] = {"candidates": [{"target_class": "android.widget.EditText"}]}

    with pytest.raises(ValidationError, match="target_class requires text_near"):
        validate_app_automation_profile(raw)


def test_rejects_region_without_real_selector_signal():
    raw = _minimal_profile()
    raw["semantic_locators"]["bad_region"] = {"candidates": [{"region": "bottom"}]}

    with pytest.raises(ValidationError, match="region must filter"):
        validate_app_automation_profile(raw)


def test_accepts_ocr_near_locator_candidate():
    raw = _minimal_profile()
    raw["semantic_locators"]["future_ocr"] = {"candidates": [{"ocr_near": "Login"}]}

    profile = validate_app_automation_profile(raw)

    assert profile.semantic_locators["future_ocr"].candidates[0].ocr_near == "Login"


def test_rejects_duplicate_watcher_names():
    raw = _minimal_profile()
    raw["popup_watchers"] = [
        {"name": "close_dialog", "when": {"text_contains": ["Update"]}, "action": {"tap_text": "Later"}},
        {"name": "close_dialog", "when": {"text_contains": ["Ad"]}, "action": {"tap_text": "Close"}},
    ]

    with pytest.raises(ValidationError, match="duplicate watcher name"):
        validate_app_automation_profile(raw)
