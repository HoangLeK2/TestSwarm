from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class FacebookReadinessStatus(StrEnum):
    READY = "ready"
    LOGGED_OUT = "logged_out"
    CHECKPOINT = "checkpoint"
    UNRESPONSIVE = "unresponsive"
    UNSUPPORTED_BUILD = "unsupported_build"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class FacebookReadinessResult:
    status: FacebookReadinessStatus
    reason: str
    attempted_at: datetime
    hierarchy_sha256: str | None = None
    app_package: str | None = None
    app_version: str | None = None
    matched_markers: tuple[str, ...] = ()

    @property
    def is_ready(self) -> bool:
        return self.status == FacebookReadinessStatus.READY

    def evidence(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["attempted_at"] = self.attempted_at.isoformat()
        data["matched_markers"] = list(self.matched_markers)
        return {
            key: value for key, value in data.items() if value not in (None, [], ())
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized(value: str | None) -> str:
    raw = unicodedata.normalize("NFKC", value or "")
    raw = raw.casefold()
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def _attrs_blob(root: ET.Element) -> str:
    parts: list[str] = []
    for node in root.iter():
        for key in ("resource-id", "text", "content-desc", "class", "package"):
            value = node.attrib.get(key)
            if value:
                parts.append(value)
    return _normalized(" ".join(parts))


def _match_any(blob: str, patterns: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    matches: list[str] = []
    for name, pattern in patterns:
        if re.search(pattern, blob):
            matches.append(name)
    return tuple(matches)


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
    package: str = "com.facebook.katana",
    app_version: str | None = None,
) -> FacebookReadinessResult:
    attempted_at = _now()
    raw = hierarchy_xml or ""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None

    def result(
        status: FacebookReadinessStatus,
        reason: str,
        markers: tuple[str, ...] = (),
    ) -> FacebookReadinessResult:
        return FacebookReadinessResult(
            status=status,
            reason=reason,
            attempted_at=attempted_at,
            hierarchy_sha256=digest,
            app_package=package,
            app_version=app_version,
            matched_markers=markers,
        )

    if not raw.strip():
        return result(FacebookReadinessStatus.INCONCLUSIVE, "hierarchy_unavailable")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return result(FacebookReadinessStatus.INCONCLUSIVE, "invalid_hierarchy")

    blob = _attrs_blob(root)
    if package and package not in blob and "facebook" not in blob:
        return result(
            FacebookReadinessStatus.UNSUPPORTED_BUILD, "facebook_package_not_visible"
        )

    markers = _match_any(blob, _UNRESPONSIVE_MARKERS)
    if markers:
        return result(FacebookReadinessStatus.UNRESPONSIVE, "app_unresponsive", markers)
    markers = _match_any(blob, _CHECKPOINT_MARKERS)
    if markers:
        return result(FacebookReadinessStatus.CHECKPOINT, "checkpoint_visible", markers)
    markers = _match_any(blob, _LOGGED_OUT_MARKERS)
    if markers:
        return result(
            FacebookReadinessStatus.LOGGED_OUT, "login_surface_visible", markers
        )
    if re.search(r"\bsearch\b|tìm kiếm", blob) and re.search(
        r"\bback\b|quay lại", blob
    ):
        return result(
            FacebookReadinessStatus.READY,
            "ready_surface_visible",
            ("search_surface",),
        )
    markers = _match_any(blob, _READY_MARKERS)
    if markers:
        return result(FacebookReadinessStatus.READY, "ready_surface_visible", markers)
    return result(FacebookReadinessStatus.INCONCLUSIVE, "readiness_markers_not_found")
