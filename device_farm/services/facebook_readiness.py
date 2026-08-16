"""Facebook implementation of platform readiness detection.

Only the marker tables and the Facebook package check live here; the status enum,
result payload and hierarchy helpers are shared and come from
``services/platform_readiness.py``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from services.platform_readiness import (
    PlatformReadinessResult,
    PlatformReadinessStatus,
    attrs_blob,
    hierarchy_digest,
    match_any,
    register_readiness_resolver,
    utcnow,
)

FACEBOOK_PACKAGE = "com.facebook.katana"

_CHECKPOINT_MARKERS = (
    (
        "checkpoint",
        (
            r"\bcheckpoint\b|security check|confirm your identity|account restricted|"
            r"xác nhận danh tính|tài khoản bị hạn chế"
        ),
    ),
    (
        "two_factor",
        (
            r"\btwo[- ]?factor\b|authentication code|login code|approval required|"
            r"mã xác thực|mã đăng nhập|yêu cầu phê duyệt"
        ),
    ),
    (
        "suspicious_login",
        (
            r"suspicious login|unusual activity|secure your account|"
            r"đăng nhập đáng ngờ|hoạt động bất thường|bảo mật tài khoản"
        ),
    ),
)

_LOGGED_OUT_MARKERS = (
    ("login_button", r"\blog in\b|log into facebook|sign in|đăng nhập facebook"),
    (
        "credential_field",
        (
            r"password|email or phone|mobile number or email|mật khẩu|"
            r"số di động hoặc email"
        ),
    ),
    ("create_account", r"create new account|join facebook|tạo tài khoản mới"),
)

_READY_MARKERS = (
    (
        "home_tab",
        r"com\.facebook\.katana:id/(?:feed_tab|home_tab|tab_home)|\bhome\b|trang chủ",
    ),
    ("menu_tab", r"com\.facebook\.katana:id/(?:bookmark_tab|menu_tab)|\bmenu\b"),
    (
        "composer",
        (
            r"what'?s on your mind|write something|create post|"
            r"bạn đang nghĩ gì|tạo bài viết"
        ),
    ),
    ("feed", r"news feed|stories|reels"),
    (
        "search_results",
        r"search results in (?:the )?tab|kết quả tìm kiếm trong tab",
    ),
)

_UNRESPONSIVE_MARKERS = (
    ("crash", r"facebook isn'?t responding|app isn'?t responding|has stopped"),
    ("system_dialog", r"close app|wait|app info"),
)


def resolve_facebook_readiness(
    hierarchy_xml: str | None,
    *,
    package: str = FACEBOOK_PACKAGE,
    app_version: str | None = None,
) -> PlatformReadinessResult:
    attempted_at = utcnow()
    raw = hierarchy_xml or ""
    digest = hierarchy_digest(raw)

    def result(
        status: PlatformReadinessStatus,
        reason: str,
        markers: tuple[str, ...] = (),
    ) -> PlatformReadinessResult:
        return PlatformReadinessResult(
            status=status,
            reason=reason,
            attempted_at=attempted_at,
            hierarchy_sha256=digest,
            app_package=package,
            app_version=app_version,
            matched_markers=markers,
            platform="facebook",
        )

    if not raw.strip():
        return result(PlatformReadinessStatus.INCONCLUSIVE, "hierarchy_unavailable")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return result(PlatformReadinessStatus.INCONCLUSIVE, "invalid_hierarchy")

    blob = attrs_blob(root)
    if package and package not in blob and "facebook" not in blob:
        return result(
            PlatformReadinessStatus.UNSUPPORTED_BUILD, "facebook_package_not_visible"
        )

    markers = match_any(blob, _UNRESPONSIVE_MARKERS)
    if markers:
        return result(PlatformReadinessStatus.UNRESPONSIVE, "app_unresponsive", markers)
    markers = match_any(blob, _CHECKPOINT_MARKERS)
    if markers:
        return result(PlatformReadinessStatus.CHECKPOINT, "checkpoint_visible", markers)
    markers = match_any(blob, _LOGGED_OUT_MARKERS)
    if markers:
        return result(
            PlatformReadinessStatus.LOGGED_OUT, "login_surface_visible", markers
        )
    if re.search(r"\bsearch\b|tìm kiếm", blob) and re.search(
        r"\bback\b|quay lại", blob
    ):
        return result(
            PlatformReadinessStatus.READY,
            "ready_surface_visible",
            ("search_surface",),
        )
    markers = match_any(blob, _READY_MARKERS)
    if markers:
        return result(PlatformReadinessStatus.READY, "ready_surface_visible", markers)
    return result(PlatformReadinessStatus.INCONCLUSIVE, "readiness_markers_not_found")


register_readiness_resolver("facebook", resolve_facebook_readiness)
