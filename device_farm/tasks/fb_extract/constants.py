from __future__ import annotations

import re
from typing import Optional, Tuple

from .shared import COMMENT_BUTTON_TOKENS, XPATH_LIST, XPATH_RECYCLER

_RE_TS = re.compile(
    r"(\d+\s*(giây|phút|giờ|ngày|tuần|tháng|năm)\s*(trước)?)"
    r"|(\d+\s*(second|minute|hour|day|week|month|year)s?\s*ago)"
    r"|(\d+\s*(min|mins|hr|hrs|d|w|mo|y)\b)"
    r"|(\bhace\s+\d+[\w\s]{0,40})"
    r"|(\bil y a\s+\d+[\w\s.'-]{0,40})"
    r"|(\bvor\s+\d+[\w\s]{0,40})"
    r"|(hôm qua|yesterday|just now|vừa xong|bây giờ|now)"
    r"|(T\d,\s*\d{1,2}/\d{1,2}/\d{4})"
    r"|(\d{1,2}/\d{1,2}/\d{4})"
    r"|(\d{1,2}\s*thg\s*\d{1,2}(?:,\s*\d{4})?)"
    r"|(\d{1,2}\s*tháng\s*\d{1,2}(?:,\s*\d{4})?)"
    r"|(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_MAX_TS_ANCHOR_NODE_LEN = 96

_RE_REEL_TYPE = re.compile(r"\breels?\b", re.IGNORECASE)
_RE_VIDEO_TYPE = re.compile(r"\b(video|clip|thước phim|watch video|xem video)\b", re.IGNORECASE)
_RE_IMAGE_TYPE = re.compile(r"^(ảnh|photo|hình|image|picture)\b", re.IGNORECASE)
_RE_FB_CAROUSEL = re.compile(r"(?:ảnh|photo|image)\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_RE_LINK_TYPE = re.compile(
    r"(https?://\S{6,}|www\.[^\s]{4,}|(?:fb|m)\.me/|fb\.watch/|l\.facebook\.com/|"
    r"\.\bcom\b|\.\bvn\b|\.\bnet\b|visit site|xem trang|đọc thêm)",
    re.IGNORECASE,
)
_RE_POST_RESHARE_HEADER = re.compile(
    r"đã\s+chia\s+sẻ\s+(một\s+)?(bài\s+viết|liên\s+kết|ảnh|video|bài\s+đăng)\b|"
    r"chia\s+sẻ\s+một\s+(bài\s+viết|liên\s+kết)\b|"
    r"\bshared\s+(?:by|from)\b|\breposted\b|"
    r"\bshared\s+a\s+(post|link|photo|video|memory)\b|"
    r"đăng\s+lại|được\s+đăng\s+lại|chia\s+sẻ\s+lại|"
    r"bài\s+viết\s+gốc|bài\s+đăng\s+gốc",
    re.IGNORECASE,
)

_RE_NUM = r"(\d[\d.,]*[KMkm]?)"
_RE_REACTIONS = re.compile(r"[^\d]*" + _RE_NUM + r"\s*(lượt thích|reactions?|likes?)?\s*$", re.IGNORECASE)
_RE_COMMENTS = re.compile(r"[^\d]*" + _RE_NUM + r"\s*(bình luận|comments?|phản hồi)\s*$", re.IGNORECASE)
_RE_SHARES = re.compile(r"[^\d]*" + _RE_NUM + r"\s*(lượt chia sẻ|shares?)\s*$", re.IGNORECASE)
_RE_VIEWS = re.compile(r"[^\d]*" + _RE_NUM + r"\s*(lượt xem|views?|lần xem)\s*$", re.IGNORECASE)
_RE_COMBINED_STATS = re.compile(
    r"(\d[\d.,]*[KMkm]?)\s*(lượt thích|reactions?|likes?|bình luận|comments?|phản hồi|lượt chia sẻ|shares?|lượt xem|views?)?",
    re.IGNORECASE,
)
_RE_LIKE_BTN_DESC = re.compile(r"^(\d[\d.,]*[KMkm]?)\s+lượt thích[.\s]", re.IGNORECASE)

_NOISE_TEXTS = frozenset({
    "·", "•", "like", "thích", "comment", "bình luận", "share", "chia sẻ",
    "follow", "theo dõi", "send", "gửi", "see more", "xem thêm", "see less", "thu gọn",
    "view post", "xem bài viết", "reply", "trả lời", "most relevant", "phù hợp nhất",
})
_NOISE_PREFIXES = (
    "lựa chọn khác cho bài viết",
    "nút bình luận",
    "nút chia sẻ",
    "thước phim",
    "action chip profile picture",
)
_NOISE_CONTAINS = (
    "bảng ở cạnh", "mở tin của", "tin chưa xem", "có dùng ai", "xem thước phim",
    "thước phim", "trạng thái hoạt động", "đã chỉnh sửa",
)

_AUTHOR_PREFIXES: Tuple[str, ...] = (
    "ảnh đại diện của",
    "profile picture of",
    "profile photo of",
    "lựa chọn khác cho bài viết của",
)


def _author_prefix_match(desc_lower: str) -> Optional[str]:
    for p in _AUTHOR_PREFIXES:
        if desc_lower.startswith(p):
            return p
    return None


_AD_RESOURCE_IDS = frozenset({
    "com.facebook.katana:id/sponsored_label",
    "com.facebook.katana:id/ad_unit_container",
    "com.facebook.lite:id/sponsored_label",
})

_VIDEO_CLASSES = frozenset({
    "android.view.SurfaceView",
    "android.widget.VideoView",
    "android.media.VideoView",
})
_MIN_IMAGE_AREA_FOR_PHOTO_HINT = 55_000

_RE_FB_GROUP_POST = re.compile(r"(?:https?://)?(?:[\w.-]+\.)?facebook\.com/groups/(\d+)/posts/(\d+)", re.I)
_RE_FB_GROUP_PERM = re.compile(r"(?:https?://)?(?:[\w.-]+\.)?facebook\.com/groups/(\d+)/permalink/(\d+)", re.I)
_RE_FB_POST_SLUG = re.compile(r"/posts/(\d{8,})\b", re.I)
_RE_FB_STORY_FBID = re.compile(r"story_fbid=(\d+)", re.I)
_RE_RES_REEL = re.compile(r"reel", re.I)
_RE_RES_VIDEO = re.compile(r"(video|player|exoplayer|mediaplayer|muxer)", re.I)

_RE_NUMERIC_SHORT = re.compile(r"^\d{1,4}$")
_RE_SHARES_COUNT_LABEL = re.compile(r"^\d+\s+lượt chia sẻ\s*$", re.IGNORECASE)
_RE_COMMENT_REACTIONS_LABEL = re.compile(r"^\d+\s+cảm xúc\s*$", re.IGNORECASE)

_LOGIN_SCREEN_MARKERS = (
    "đăng nhập", "log in", "log into facebook", "enter password", "quên mật khẩu", "forgot password",
)
_RATE_LIMIT_MARKERS = (
    "temporarily blocked", "tạm thời bị chặn", "you're temporarily blocked", "bạn đã bị chặn tạm thời", "try again later", "thử lại sau",
)

_RE_CMT_LIKE_BTN = re.compile(r"^Nút Thích bình luận của (.+?)\.", re.IGNORECASE)
_RE_CMT_REPLY_BTN = re.compile(r"^Trả lời bình luận của (.+?),", re.IGNORECASE)
_RE_CMT_REACTIONS = re.compile(r"^(\d[\d.,]*[KMkm]?)\s+cảm xúc$", re.IGNORECASE)
_RE_CMT_REACTIONS_EN = re.compile(r"^(\d[\d.,]*[KMkm]?)\s+reactions?\s*$", re.IGNORECASE)
_RE_CMT_TS_SHARE = re.compile(r"•\s*Chia sẻ với.*$", re.IGNORECASE)
_RE_COMMENT_NAME_DOT_SUFFIX = re.compile(r"^(.{2,60}?)\s*[•·]\s*(.+)$")
_RE_LEAKED_REL_TIME_AS_LABEL = re.compile(
    r"^\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm)\s*(?:trước)?$",
    re.IGNORECASE,
)

_CMT_NOISE_TEXTS = frozenset({
    "thích", "trả lời", "like", "reply", "xem thêm câu trả lời", "ẩn câu trả lời",
    "theo dõi", "· theo dõi", "menu", "delete", "tìm kiếm", "space",
})
_CMT_EMPTY_BODY_JUNK_AUTHOR = frozenset({
    "menu", "delete", "tìm kiếm", "space", "người đóng góp nổi bật", "người đóng góp đang lên",
    "người đóng góp nhiều nhất", "cảm xúc", "gỡ", "video sound toggle", "openclaw vn",
    "tham gia", "truy cập", "tác giả", "you", "to",
})
_CMT_BADGE_LABELS = frozenset({
    "người đóng góp nổi bật", "người đóng góp đang lên", "người đóng góp nhiều nhất",
    "top fan", "fan cứng", "siêu fan", "super fan", "rising creator", "friend",
    "được mời", "người ảnh hưởng", "chuyên gia", "pre-broadcast contributor",
    "người hâm mộ", "subscriber", "đăng ký theo dõi", "fan cuồng", "người hay tương tác",
})

