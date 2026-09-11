from __future__ import annotations

from services.facebook_readiness import resolve_facebook_readiness
from services.platform_readiness import PlatformReadinessStatus


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

    assert result.status == PlatformReadinessStatus.READY
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

    assert result.status == PlatformReadinessStatus.LOGGED_OUT
    assert result.reason == "login_surface_visible"


def test_readiness_checkpoint_wins_over_login_markers():
    xml = _hierarchy(
        '<node package="com.facebook.katana" text="Confirm your identity" />',
        '<node package="com.facebook.katana" text="Log in" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.CHECKPOINT
    assert result.reason == "checkpoint_visible"


def test_readiness_detects_vietnamese_selfie_video_verification_as_checkpoint():
    xml = _hierarchy(
        '<node package="com.facebook.katana" text="Quay video selfie để xác nhận '
        'bạn là người thật" />',
        '<node package="com.facebook.katana" text="Chúng tôi cần có thêm thông tin '
        'để đảm bảo bạn là người thật." />',
        '<node package="com.facebook.katana" text="Video selfie bạn gửi sẽ chỉ được '
        'dùng để xác nhận danh tính của bạn và đảm bảo an toàn cho cộng đồng." />',
        '<node package="com.facebook.katana" text="Chúng tôi sẽ xóa video này trong '
        'vòng 30 ngày." />',
        '<node package="com.facebook.katana" class="android.widget.Button" '
        'content-desc="Bắt đầu quay video selfie" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.CHECKPOINT
    assert result.reason == "checkpoint_visible"
    assert "selfie_video_verification" in result.matched_markers


def test_readiness_does_not_treat_selfie_video_post_as_checkpoint():
    xml = _hierarchy(
        '<node package="com.facebook.katana" resource-id="com.facebook.katana:id/feed_tab" '
        'content-desc="Trang chủ" />',
        '<node package="com.facebook.katana" text="Mẹo quay video selfie để xác nhận '
        'bạn là người thật khi cần." />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.READY


def test_readiness_detects_vietnamese_suspended_account_as_checkpoint():
    xml = _hierarchy(
        '<node package="com.facebook.katana" text="Chúng tôi đã đình chỉ tài khoản '
        'của bạn" />',
        '<node package="com.facebook.katana" text="Bạn còn 168 ngày để kháng nghị '
        'trước khi chúng tôi vô hiệu hóa vĩnh viễn tài khoản của bạn" />',
        '<node package="com.facebook.katana" text="Tài khoản của bạn có thể liên '
        'quan đến một tài khoản khác vi phạm quy tắc của chúng tôi." />',
        '<node package="com.facebook.katana" class="android.widget.Button" '
        'content-desc="Kháng nghị" />',
        '<node package="com.facebook.katana" class="android.widget.Button" '
        'content-desc="Đăng xuất" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.CHECKPOINT
    assert result.reason == "checkpoint_visible"
    assert "account_suspended_verification" in result.matched_markers


def test_readiness_does_not_treat_suspension_discussion_post_as_checkpoint():
    xml = _hierarchy(
        '<node package="com.facebook.katana" resource-id="com.facebook.katana:id/feed_tab" '
        'content-desc="Trang chủ" />',
        '<node package="com.facebook.katana" text="Bài viết giải thích vì sao một '
        'tài khoản của bạn có thể bị đình chỉ." />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.READY


def test_readiness_rejects_non_facebook_hierarchy():
    xml = _hierarchy('<node package="com.android.settings" text="Home" />')

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.UNSUPPORTED_BUILD


def test_readiness_handles_invalid_or_empty_hierarchy():
    assert resolve_facebook_readiness("").status == PlatformReadinessStatus.INCONCLUSIVE
    assert resolve_facebook_readiness("<hierarchy>").reason == "invalid_hierarchy"


def test_readiness_detects_vietnamese_login_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" text="Số di động hoặc email" />',
        '<node package="com.facebook.katana" text="Mật khẩu" />',
        '<node package="com.facebook.katana" text="Đăng nhập" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.LOGGED_OUT
    assert "credential_field" in result.matched_markers


def test_readiness_detects_vietnamese_home_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" content-desc="Trang chủ" />',
        '<node package="com.facebook.katana" text="Bạn đang nghĩ gì?" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.READY
    assert "home_tab" in result.matched_markers


def test_readiness_detects_authenticated_search_results_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" '
        'content-desc="Kết quả tìm kiếm trong tab Mọi người, 2 trong số 7" />',
        '<node package="com.facebook.katana" text="Mọi người" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.READY
    assert "search_results" in result.matched_markers


def test_readiness_detects_authenticated_search_input_surface():
    xml = _hierarchy(
        '<node package="com.facebook.katana" content-desc="Quay lại" />',
        '<node package="com.facebook.katana" class="android.widget.EditText" '
        'content-desc="Tìm kiếm" text="Nguyễn Tuấn Anh Osana" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.READY
    assert result.matched_markers == ("search_surface",)


def test_readiness_detects_vietnamese_entry_screen_as_logged_out():
    """Dumped from a V2352A sitting on the logged-out entry screen.

    The Vietnamese wording carries none of the English login tokens, so this
    screen used to resolve INCONCLUSIVE and the preflight gate refused to start
    the login on a phone that was plainly signed out.
    """
    xml = _hierarchy(
        '<node package="com.facebook.katana" text="Tiếng Việt" content-desc="Tiếng Việt" />',
        '<node package="com.facebook.katana" text="Tham gia Facebook" '
        'content-desc="Tham gia Facebook" />',
        '<node package="com.facebook.katana" class="android.widget.Button" '
        'content-desc="Bắt đầu" />',
        '<node package="com.facebook.katana" class="android.widget.Button" '
        'content-desc="Tôi có trang cá nhân rồi" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.LOGGED_OUT
    assert result.matched_markers == ("entry_screen",)


def test_readiness_does_not_read_a_quoted_headline_as_a_logged_out_screen():
    """The pair is the marker; the headline alone is not.

    A signed-in feed carrying a post that quotes "Tham gia Facebook" must not
    be sent back through a full re-login.
    """
    xml = _hierarchy(
        '<node package="com.facebook.katana" resource-id="com.facebook.katana:id/feed_tab" '
        'content-desc="Trang chủ" />',
        '<node package="com.facebook.katana" text="Mời bạn bè tham gia Facebook nhé" />',
    )

    result = resolve_facebook_readiness(xml)

    assert result.status == PlatformReadinessStatus.READY
