"""Lightweight incident detection for scenario recovery."""
from __future__ import annotations

import concurrent.futures
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


_POPUP_TEXT = (
    "not now", "maybe later", "turn on notifications",
    "save your login", "sync contacts", "find friends", "try again",
    "ok", "got it", "continue", "skip",
    "không phải bây giờ", "để sau", "bật thông báo", "đồng bộ danh bạ",
)
_CHECKPOINT_TEXT = (
    "checkpoint", "captcha", "log in", "login", "session expired",
    "confirm your identity", "account locked", "verify", "password",
    "đăng nhập", "xác minh", "tài khoản bị khóa", "mật khẩu",
)

_PROFILE_TEXT = (
    "add friend", "message", "friends", "followers", "posts", "photos",
    "thêm bạn bè", "nhắn tin", "bạn bè", "người theo dõi", "ảnh",
)
_COMMENT_SHEET_TEXT = (
    "write a comment", "most relevant", "all comments", "comment as",
    "viết bình luận", "phù hợp nhất", "tất cả bình luận",
)
_POST_DETAIL_TEXT = (
    "like", "comment", "share", "send", "thích", "bình luận", "chia sẻ", "gửi",
)


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    xml: str | None = None
    screenshot_b64: str | None = None
    package_name: str | None = None
    activity_name: str | None = None
    hierarchy_hash: str | None = None


@dataclass(frozen=True, slots=True)
class Incident:
    type: str
    confidence: float
    reason_code: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "incident_type": self.type,
            "confidence": round(float(self.confidence), 3),
            "reason_code": self.reason_code,
            "evidence": self.evidence,
        }


def _norm(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def _contains_any(haystack: str, needles: tuple[str, ...]) -> str | None:
    for needle in needles:
        if needle in haystack:
            return needle
    return None


def _hierarchy_hash(xml: str | None) -> str | None:
    if not xml:
        return None
    return hashlib.sha1(re.sub(r"\s+", " ", xml).encode("utf-8", "ignore")).hexdigest()


def capture_snapshot(device: Any, *, timeout_s: float = 2.0) -> ScreenSnapshot:
    xml: str | None = None

    def _load_xml() -> str | None:
        fn = getattr(device, "hierarchy_xml", None)
        if not callable(fn):
            return None
        try:
            return fn(force_refresh=False)
        except TypeError:
            return fn()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            xml = pool.submit(_load_xml).result(timeout=timeout_s)
    except Exception:
        xml = None

    return ScreenSnapshot(
        xml=xml if isinstance(xml, str) else None,
        package_name=str(getattr(device, "current_package", "") or "") or None,
        activity_name=str(getattr(device, "current_activity", "") or "") or None,
        hierarchy_hash=_hierarchy_hash(xml if isinstance(xml, str) else None),
    )


def detect_incident(
    *,
    device: Any,
    step: dict[str, Any],
    step_result: dict[str, Any] | None = None,
    snapshot: ScreenSnapshot | None = None,
) -> Incident | None:
    step_result = step_result or {}
    message = _norm(str(step_result.get("message") or ""))
    reason_code = _norm(str(step_result.get("reason_code") or ""))
    result_text = f"{reason_code} {message}".strip()

    if _contains_any(result_text, _CHECKPOINT_TEXT):
        return Incident("login_or_checkpoint", 0.95, "login_or_checkpoint", {"source": "step_result"})
    if "no-growth" in result_text or "no_new" in result_text or "stuck" in result_text:
        return Incident("stuck_screen", 0.75, "stuck_screen", {"source": "step_result"})
    if "comment sheet" in result_text and ("not" in result_text or "miss" in result_text):
        return Incident("comment_panel_closed", 0.8, "comment_panel_closed", {"source": "step_result"})

    if snapshot is None:
        snapshot = capture_snapshot(device)
    xml_text = _norm(snapshot.xml)
    if not xml_text:
        return None

    matched = _contains_any(xml_text, _CHECKPOINT_TEXT)
    if matched:
        return Incident("login_or_checkpoint", 0.95, "login_or_checkpoint", {"matched": matched})

    matched = _contains_any(xml_text, _POPUP_TEXT)
    if matched:
        return Incident("app_popup", 0.82, "app_popup", {"matched": matched})

    strategy = str(step.get("strategy") or "")
    if strategy in {"comments", "platform_comments"}:
        comment_marker = _contains_any(xml_text, _COMMENT_SHEET_TEXT)
        if comment_marker:
            return None
        profile_marker = _contains_any(xml_text, _PROFILE_TEXT)
        if profile_marker and not _contains_any(xml_text, _POST_DETAIL_TEXT):
            return Incident("profile_page", 0.78, "profile_page", {"matched": profile_marker})
        if not _contains_any(xml_text, _POST_DETAIL_TEXT):
            return Incident("lost_post_detail", 0.72, "lost_post_detail", {"strategy": strategy})

    return None
