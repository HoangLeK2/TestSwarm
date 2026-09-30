from __future__ import annotations

import importlib


migration = importlib.import_module(
    "db.migrations.138_facebook_login_password_method_continue"
)


def _body() -> dict:
    return {
        "steps": [
            {
                "type": "if_variable",
                "else": [
                    {
                        "type": "login_if_needed",
                        "profile": {
                            "package": "com.facebook.katana",
                            "login_recipe": {
                                "post_submit_actions": [
                                    {
                                        "when_text_exact_any": [
                                            "Chọn cách xác nhận tài khoản",
                                            "Choose a way to confirm your account",
                                        ],
                                        "tap_text_any": ["Mật khẩu", "Password"],
                                    },
                                    {
                                        "when_text_any": ["Đang chờ phê duyệt"],
                                        "tap_text_any": ["Thử cách khác"],
                                    },
                                ]
                            },
                        },
                    }
                ],
            }
        ]
    }


def test_inserts_continue_immediately_after_password_method() -> None:
    body = _body()

    assert migration._insert_password_method_continue(body) == 1

    actions = body["steps"][0]["else"][0]["profile"]["login_recipe"][
        "post_submit_actions"
    ]
    assert actions[0]["tap_text_any"] == ["Mật khẩu", "Password"]
    assert actions[1]["tap_text_any"] == ["Tiếp tục", "Continue", "Next"]


def test_password_method_migration_is_idempotent() -> None:
    body = _body()

    assert migration._insert_password_method_continue(body) == 1
    assert migration._insert_password_method_continue(body) == 0
