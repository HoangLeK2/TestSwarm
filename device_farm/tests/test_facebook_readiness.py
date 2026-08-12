from __future__ import annotations

from services.facebook_readiness import (
    FacebookReadinessStatus,
    resolve_facebook_readiness,
)


def _hierarchy(*nodes: str) -> str:
    return "<hierarchy>" + "".join(nodes) + "</hierarchy>"


def test_readiness_detects_ready_home_surface_without_identity_inference():
    xml = _hierarchy(
        '<node package="com.facebook.katana" resource-id="com.facebook.katana:id/feed_tab" '
        'content-desc="Home" />',
        '<node package="com.facebook.katana" text="What\'s on your mind?" />',
        '<node package="com.facebook.katana" text="Jane Example" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == FacebookReadinessStatus.READY
    assert result.reason == "ready_surface_visible"
    assert result.hierarchy_sha256
    assert "Jane Example" not in str(result.evidence())


def test_readiness_detects_logged_out_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" text="Email or phone" />',
        '<node package="com.facebook.katana" text="Password" />',
        '<node package="com.facebook.katana" text="Log in" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == FacebookReadinessStatus.LOGGED_OUT
    assert result.reason == "login_surface_visible"


def test_readiness_checkpoint_wins_over_login_markers():
    xml = _hierarchy(
        '<node package="com.facebook.katana" text="Confirm your identity" />',
        '<node package="com.facebook.katana" text="Log in" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == FacebookReadinessStatus.CHECKPOINT
    assert result.reason == "checkpoint_visible"


def test_readiness_rejects_non_facebook_hierarchy():
    xml = _hierarchy('<node package="com.android.settings" text="Home" />')

    result = resolve_facebook_readiness(xml)

    assert result.status == FacebookReadinessStatus.UNSUPPORTED_BUILD


def test_readiness_handles_invalid_or_empty_hierarchy():
    assert resolve_facebook_readiness("").status == FacebookReadinessStatus.INCONCLUSIVE
    assert resolve_facebook_readiness("<hierarchy>").reason == "invalid_hierarchy"


def test_readiness_detects_vietnamese_login_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" text="Số di động hoặc email" />',
        '<node package="com.facebook.katana" text="Mật khẩu" />',
        '<node package="com.facebook.katana" text="Đăng nhập" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == FacebookReadinessStatus.LOGGED_OUT
    assert "credential_field" in result.matched_markers


def test_readiness_detects_vietnamese_home_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" content-desc="Trang chủ" />',
        '<node package="com.facebook.katana" text="Bạn đang nghĩ gì?" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == FacebookReadinessStatus.READY
    assert "home_tab" in result.matched_markers


def test_readiness_detects_authenticated_search_results_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" '
        'content-desc="Kết quả tìm kiếm trong tab Mọi người, 2 trong số 7" />',
        '<node package="com.facebook.katana" text="Mọi người" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == FacebookReadinessStatus.READY
    assert "search_results" in result.matched_markers


def test_readiness_detects_authenticated_search_input_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" content-desc="Quay lại" />',
        '<node package="com.facebook.katana" class="android.widget.EditText" '
        'content-desc="Tìm kiếm" text="Nguyễn Tuấn Anh Osana" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == FacebookReadinessStatus.READY
    assert result.matched_markers == ("search_surface",)
