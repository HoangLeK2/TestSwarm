from services.scenario_migrations.platform_session_cleanup import (
    cleanup_platform_session_body,
)


def test_cleanup_keeps_login_flow_session_nodes():
    body = {
        "steps": [
            {"type": "platform_session_gate", "phase": "preflight"},
            {
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "then": [{"type": "wait", "seconds": 1}],
                "else": [{"type": "login_if_needed"}],
            },
        ]
    }

    result = cleanup_platform_session_body(body, name="Đăng nhập Facebook")

    assert result.changed is False
    assert result.classification == "login_flow_keep"


def test_cleanup_unwraps_auth_required_flow_and_adds_requirement():
    body = {
        "steps": [
            {"type": "launch_app", "package": "com.facebook.katana"},
            {"type": "platform_session_gate", "phase": "preflight"},
            {
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "then": [{"type": "social_scan_posts_interact"}],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ]
    }

    result = cleanup_platform_session_body(
        body,
        name="Nuôi Facebook - Tương tác bài viết trên Feed",
        tags="facebook,nurture,interaction",
    )

    assert result.changed is True
    assert result.classification == "auth_required_rewrite"
    assert result.removed_gate_count == 1
    assert result.removed_ready_condition_count == 1
    assert result.body["steps"] == [
        {"type": "launch_app", "package": "com.facebook.katana"},
        {"type": "social_scan_posts_interact"},
    ]
    assert result.body["requirements"]["platform_session"] == {
        "required": True,
        "platform": "facebook",
        "account_source": "device_primary",
    }


def test_cleanup_does_not_keep_normal_flow_just_because_old_else_logged_in():
    body = {
        "steps": [
            {"type": "platform_session_gate", "phase": "preflight"},
            {
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "then": [{"type": "content_interaction"}],
                "else": [{"type": "login_if_needed"}],
            },
        ]
    }

    result = cleanup_platform_session_body(
        body,
        name="Đăng bài Facebook rồi like/comment copy",
        tags="facebook,publish",
    )

    assert result.classification == "auth_required_rewrite"
    assert result.body["steps"] == [{"type": "content_interaction"}]


def test_cleanup_unwraps_public_flow_without_requirement():
    body = {
        "requirements": {
            "platform_session": {
                "required": True,
                "platform": "facebook",
                "account_source": "device_primary",
            }
        },
        "steps": [
            {"type": "platform_session_gate", "phase": "preflight"},
            {
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "then": [{"type": "extract", "entity": "pages"}],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    }

    result = cleanup_platform_session_body(
        body,
        name="Khám phá Page Facebook theo keyword",
        tags="facebook,page,discovery",
    )

    assert result.changed is True
    assert result.classification == "public_rewrite"
    assert result.body == {"steps": [{"type": "extract", "entity": "pages"}]}
