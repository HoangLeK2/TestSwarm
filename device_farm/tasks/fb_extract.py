"""
fb_extract.py — Facebook post parsing utilities.

Extracted from fb_group_crawl.py; contains only the XML parsing / extraction
helpers used by scenario_task.py (extract step, fb_posts strategy).
No crawl job / DB / network code here.

Scope notes (single-snapshot parser):
- Pagination, cross-page dedup, and end-of-feed detection live in the executor
  (scroll loops + _dedup), not here.
- Real `fb_post_id` / permalinks are only present when the hierarchy exposes
  URLs (link preview, share text). Most feed rows still rely on synthetic ids.
- Comment `indent_level` is a layout hint only; collapsed threads and non-x
  layouts can mis-rank depth.
- **Post ↔ ảnh / media:** Trong hierarchy, mỗi **node con trực tiếp** của
  `RecyclerView` (thuộc tính `index="0"`, `index="1"`, …) là một bài viết.
  Mọi `bounds` / `content-desc` kiểu ``Ảnh 1/3`` nằm trong cùng subtree đó
  thuộc cùng bài; `feed_item_index` + `media_artifacts` phản ánh điều này.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree as _lxml

log = logging.getLogger(__name__)

# ── Timestamp regex (Vietnamese + English) ────────────────────────────────────

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
    r"|(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)

# Time rows in the post header are short. Long bodies often contain phrases like
# "1 tuần" / "3 days" — do not treat those nodes as the timestamp anchor.
_MAX_TS_ANCHOR_NODE_LEN = 96

_RE_REEL_TYPE = re.compile(r"\breels?\b", re.IGNORECASE)
_RE_VIDEO_TYPE = re.compile(
    r"\b(video|clip|thước phim|watch video|xem video)\b", re.IGNORECASE
)
_RE_IMAGE_TYPE = re.compile(
    r"^(ảnh|photo|hình|image|picture)\b", re.IGNORECASE
)
# Carousel / album: "Ảnh 1/3, mở rộng ảnh" (content-desc on Button)
_RE_FB_CAROUSEL = re.compile(
    r"(?:ảnh|photo|image)\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE
)
_RE_LINK_TYPE = re.compile(
    r"(https?://\S{6,}|www\.[^\s]{4,}|"
    r"(?:fb|m)\.me/|fb\.watch/|l\.facebook\.com/|"
    r"\.\bcom\b|\.\bvn\b|\.\bnet\b|visit site|xem trang|đọc thêm)",
    re.IGNORECASE,
)
# Đoạn header “đã chia sẻ bài…” (bài gắn / reshare) — gợi ý post_type link kèm URL/permalink.
_RE_POST_RESHARE_HEADER = re.compile(
    r"đã\s+chia\s+sẻ\s+(một\s+)?(bài\s+viết|liên\s+kết|ảnh|video|bài\s+đăng)\b|"
    r"chia\s+sẻ\s+một\s+(bài\s+viết|liên\s+kết)\b|"
    r"\bshared\s+(?:by|from)\b|\breposted\b|"
    r"\bshared\s+a\s+(post|link|photo|video|memory)\b|"
    r"đăng\s+lại|được\s+đăng\s+lại|chia\s+sẻ\s+lại|"
    r"bài\s+viết\s+gốc|bài\s+đăng\s+gốc",
    re.IGNORECASE,
)

# Số có thể đứng sau emoji/ký tự bất kỳ, format: 1.2K / 1,2K / 123 / 1.200
_RE_NUM = r"(\d[\d.,]*[KMkm]?)"

_RE_REACTIONS = re.compile(
    r"[^\d]*" + _RE_NUM + r"\s*(lượt thích|reactions?|likes?)?\s*$", re.IGNORECASE
)
_RE_COMMENTS = re.compile(
    r"[^\d]*" + _RE_NUM + r"\s*(bình luận|comments?|phản hồi)\s*$", re.IGNORECASE
)
_RE_SHARES = re.compile(
    r"[^\d]*" + _RE_NUM + r"\s*(lượt chia sẻ|shares?)\s*$", re.IGNORECASE
)
_RE_VIEWS = re.compile(
    r"[^\d]*" + _RE_NUM + r"\s*(lượt xem|views?|lần xem)\s*$", re.IGNORECASE
)
# Combined stats node: "1,2K · 45 bình luận · 12 lượt chia sẻ"
_RE_COMBINED_STATS = re.compile(
    r"(\d[\d.,]*[KMkm]?)\s*"
    r"(lượt thích|reactions?|likes?|bình luận|comments?|phản hồi"
    r"|lượt chia sẻ|shares?|lượt xem|views?)?",
    re.IGNORECASE,
)
# content-desc nút like: "1.200 lượt thích. Nút Thích." → trích số
_RE_LIKE_BTN_DESC = re.compile(
    r"^(\d[\d.,]*[KMkm]?)\s+lượt thích[.\s]", re.IGNORECASE
)

_NOISE_TEXTS = frozenset({
    "·", "•", "·",
    "like", "thích", "comment", "bình luận", "share", "chia sẻ",
    "follow", "theo dõi", "send", "gửi",
    "see more", "xem thêm", "see less", "thu gọn",
    "view post", "xem bài viết",
    "reply", "trả lời",
    "most relevant", "phù hợp nhất",
})

_NOISE_PREFIXES = (
    "lựa chọn khác cho bài viết",
    "nút bình luận",
    "nút chia sẻ",
    "thước phim",
    "action chip profile picture",
)
# "nút thích" không bỏ vào noise vì content-desc có thể chứa số like:
# "1.200 lượt thích. Nút Thích." → cần parse trước rồi skip

# Prefix dùng để trích xuất tên tác giả từ content-desc avatar
_AUTHOR_PREFIX = "ảnh đại diện của"

_NOISE_CONTAINS = (
    "bảng ở cạnh",
    "mở tin của",
    "tin chưa xem",
    "có dùng ai",
    "xem thước phim",
    "thước phim",
    "trạng thái hoạt động",
    "đã chỉnh sửa",
)

# Post *body* still folded / lazy — same markers used by extract retry + quality scoring.
_TRUNCATION_MARKERS: Tuple[str, ...] = (
    "xem thêm",
    "see more",
    "view more",
    "xem thêm bình luận",
    "view more comments",
    "xem thêm câu trả lời",
    "view more replies",
)


def is_fb_post_truncated(post: Dict[str, Any]) -> bool:
    """True if parsed post text still contains a see-more style fold marker."""
    t = (post.get("text") or "").lower()
    return any(m in t for m in _TRUNCATION_MARKERS)

_AD_RESOURCE_IDS = frozenset({
    "com.facebook.katana:id/sponsored_label",
    "com.facebook.katana:id/ad_unit_container",
    "com.facebook.lite:id/sponsored_label",
})

_LXML_PARSER = _lxml.XMLParser(recover=True, remove_comments=True, encoding="utf-8")

# Main FB feed often uses StaggeredGridLayoutManager, not RecyclerView class name.
_XPATH_RECYCLER = (
    '//node[contains(@class, "RecyclerView") and @scrollable="true"]'
    '|//node[contains(@class, "StaggeredGridLayoutManager") and @scrollable="true"]'
)
_XPATH_LIST = '//node[contains(@class, "ListView") and @scrollable="true"]'

_VIDEO_CLASSES = frozenset({
    "android.view.SurfaceView",
    "android.widget.VideoView",
    "android.media.VideoView",
})
# Large inline preview — locale-independent vs "Ảnh …" text.
_MIN_IMAGE_AREA_FOR_PHOTO_HINT = 55_000

_RE_FB_GROUP_POST = re.compile(
    r"(?:https?://)?(?:[\w.-]+\.)?facebook\.com/groups/(\d+)/posts/(\d+)", re.I
)
_RE_FB_GROUP_PERM = re.compile(
    r"(?:https?://)?(?:[\w.-]+\.)?facebook\.com/groups/(\d+)/permalink/(\d+)", re.I
)
_RE_FB_POST_SLUG = re.compile(r"/posts/(\d{8,})\b", re.I)
_RE_FB_STORY_FBID = re.compile(r"story_fbid=(\d+)", re.I)
_RE_RES_REEL = re.compile(r"reel", re.I)
_RE_RES_VIDEO = re.compile(r"(video|player|exoplayer|mediaplayer|muxer)", re.I)


def _parse_stats(t: str) -> Dict[str, Optional[str]]:
    """Parse một text node thành dict stats. Hỗ trợ:
    - "1,2K lượt thích" / "❤️ 1,2K" / "1.200 lượt thích. Nút Thích."
    - "45 bình luận" / "12 lượt chia sẻ" / "5,4K lượt xem"
    - Combined: "1,2K · 45 bình luận · 12 lượt chia sẻ"
    Trả về dict với các key có giá trị tìm thấy, None nếu không có.
    """
    result: Dict[str, Optional[str]] = {
        "reactions": None, "comments": None, "shares": None, "views": None,
    }
    # Thử combined trước (có dấu ·)
    if "·" in t or "•" in t:
        parts = re.split(r"[·•]", t)
        for part in parts:
            part = part.strip()
            _apply_stat(part, result)
        return result
    _apply_stat(t, result)
    return result


def _apply_stat(t: str, result: Dict[str, Optional[str]]) -> None:
    """Apply 1 đoạn text vào result dict nếu match stats pattern."""
    # Like button desc: "1.200 lượt thích. Nút Thích."
    m = _RE_LIKE_BTN_DESC.match(t)
    if m and result["reactions"] is None:
        result["reactions"] = m.group(1)
        return
    m = _RE_VIEWS.search(t)
    if m and result["views"] is None:
        result["views"] = m.group(1)
        return
    m = _RE_SHARES.search(t)
    if m and result["shares"] is None:
        result["shares"] = m.group(1)
        return
    m = _RE_COMMENTS.search(t)
    if m and result["comments"] is None:
        result["comments"] = m.group(1)
        return
    # Reactions: số đứng một mình hoặc với nhãn "lượt thích"
    m = _RE_REACTIONS.search(t)
    if m and result["reactions"] is None:
        label = (m.group(2) or "").lower()
        stripped = t.strip()
        # Không có label → chỉ số + suffix rất ngắn (tránh câu ngắn bị nhầm reaction)
        if label:
            result["reactions"] = m.group(1)
        elif len(stripped) <= 8 and re.fullmatch(
            r"[^\d]*\d[\d.,]*[KMkm]?\s*", stripped, flags=re.IGNORECASE
        ):
            result["reactions"] = m.group(1)


def _is_noise_text(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in _NOISE_TEXTS:
        return True
    if any(t.startswith(prefix) for prefix in _NOISE_PREFIXES):
        return True
    if any(token in t for token in _NOISE_CONTAINS):
        return True
    return False


def _is_post_action_delimiter(text: str) -> bool:
    """First node of the post action row (FB often omits the relative-time line)."""
    t = (text or "").strip()
    tl = t.lower()
    if tl in ("bình luận", "comment"):
        return True
    # Post row: "Nút Thích. Hãy nhấn đúp…" — comment rows use "Nút Thích bình luận của…" (no dot).
    if tl.startswith("nút thích."):
        return True
    if tl.startswith("nút chia sẻ") and "bài viết" in tl:
        return True
    return False


def _is_fb_comment_thread_chrome_row(text: str) -> bool:
    """Under-post comment block: a11y for like/reply on comments, reaction counts — not caption."""
    tl = (text or "").strip().lower()
    if tl.startswith("nút thích bình luận"):
        return True
    if tl.startswith("trả lời bình luận"):
        return True
    if _RE_COMMENT_REACTIONS_LABEL.match((text or "").strip()):
        return True
    return False


def _is_hashtag_chip(text: str) -> bool:
    """Single-line hashtag button (e.g. #openclaw) — not the post author."""
    s = (text or "").strip()
    if not s.startswith("#") or " " in s or "\n" in s:
        return False
    return len(s) < 48


_RE_NUMERIC_SHORT = re.compile(r"^\d{1,4}$")
_RE_SHARES_COUNT_LABEL = re.compile(r"^\d+\s+lượt chia sẻ\s*$", re.IGNORECASE)
_RE_COMMENT_REACTIONS_LABEL = re.compile(r"^\d+\s+cảm xúc\s*$", re.IGNORECASE)


def _post_body_has_comment_thread_a11y(text: str) -> bool:
    """True if text is mostly FB a11y strings for *comment* rows (not post Thích)."""
    t = (text or "").lower()
    markers = (
        "nút thích bình luận của",
        "trả lời bình luận của",
        "nhấn đúp để trả lời bình luận",
    )
    return sum(1 for m in markers if m in t) >= 2


def _maybe_fix_merged_feed_caption(post: Dict[str, Any]) -> None:
    """Two feed previews glued with ``**`` + second post's time row — keep first caption."""
    body = post.get("text") or ""
    if "**" not in body:
        return
    main = re.split(r"\s*\*\*\s*", body, maxsplit=1)[0].strip()
    if re.search(r"Xem thêm\s+\d+\s*(?:ngày|giờ|phút)\s*•", main, re.I):
        main = re.sub(
            r"(Xem thêm)\s+\d+\s*(?:ngày|giờ|phút)\s*•.*$",
            r"\1",
            main,
            flags=re.I,
        )
    post["text"] = main


def _refresh_post_derived_hashes(post: Dict[str, Any]) -> None:
    """Recompute _pid / stable_post_id / post_key after mutating author or body."""
    author = post.get("author") or ""
    body = post.get("text") or ""
    image_desc = post.get("image_desc")
    comment_preview = post.get("comment_preview")
    _pid_raw = f"{author or ''}\x00{body[:120]}"
    post["_pid"] = hashlib.md5(_pid_raw.encode()).hexdigest()[:16]
    _stable_prefix = unicodedata.normalize("NFC", re.sub(r"\s+", " ", body.lower()).strip())
    _stable_prefix = _stable_prefix.replace("…", "").replace("...", "")
    for _mk in _TRUNCATION_MARKERS:
        _stable_prefix = _stable_prefix.replace(_mk, "")
    _stable_prefix = _stable_prefix.strip()[:100]
    _sid_author = unicodedata.normalize("NFC", (author or "").strip().lower())
    _sid_img = unicodedata.normalize("NFC", (str(image_desc or "")).strip().lower())[:40]
    _sid_raw = f"{_sid_author}\x00{_stable_prefix}\x00{_sid_img}"
    post["stable_post_id"] = hashlib.sha1(_sid_raw.encode("utf-8")).hexdigest()
    _pk_raw = f"{author or ''}\x00{body}\x00{image_desc or ''}\x00{comment_preview or ''}"
    post["post_key"] = hashlib.sha1(_pk_raw.encode("utf-8")).hexdigest()


def _is_junk_recycler_post(post: Dict[str, Any]) -> bool:
    """Rows from comment sheets / thread chips / composer saved as feed posts — drop."""
    author = (post.get("author") or "").strip()
    text = (post.get("text") or "").strip()
    al = author.lower()
    tl = text.lower()
    combined_lc = f"{al} {tl}"

    # Album / reaction count chip mis-read as author (e.g. "+3", "12")
    if re.match(r"^\+?\d{1,3}$", author) and len(text) < 64:
        return True
    if al == "video sound toggle":
        return True
    # Like-button a11y leaked into post body
    if "nút thích." in tl and ("nhấn đúp" in tl or "double tap" in tl or "double-tap" in tl):
        return True
    # Caption bị gán nhầm: một câu có dấu phẩy làm author, không còn body
    if author and (not text or not text.strip()) and "," in author and len(author) > 22:
        return True
    # Chỉ còn tên + chip ảnh / không có nội dung thật (không carousel / preview)
    if (
        author
        and (not text or not text.strip())
        and not (post.get("image_desc") or "").strip()
        and not (post.get("media_artifacts") or [])
        and not (post.get("comment_preview") or "").strip()
        and post.get("reactions") is None
        and post.get("comments") is None
    ):
        return True
    # Author rỗng, body giống tên người (1–4 từ) — thường là đảo trường
    if (
        not author
        and text
        and len(text) < 50
        and 1 <= text.count(" ") <= 4
        and "http" not in tl
        and "•" not in text
        and not _RE_TS.search(text)
    ):
        return True
    if (
        text
        and _RE_IMAGE_TYPE.match(tl)
        and len(text) < 20
        and len(author) > 6
        and not (post.get("image_desc") or "").strip()
    ):
        return True

    if al.startswith("viết bình luận") or "viết bình luận công khai" in combined_lc:
        return True
    if al == "đóng":
        return True
    if _RE_SHARES_COUNT_LABEL.match(author):
        return True
    if _RE_COMMENT_REACTIONS_LABEL.match(author):
        return True
    if _RE_NUMERIC_SHORT.match(author) and (
        "bộ lọc bình luận" in tl
        or "phù hợp nhất" in tl
        or "đang hiển thị" in tl
    ):
        return True
    if re.search(r"^xem\s+\d+\s+phản hồi", author, re.I):
        return True
    if author.endswith(" hóng") and len(text) < 4:
        return True
    if "người đóng góp nổi bật" in al and _post_body_has_comment_thread_a11y(text):
        return True
    if author == "Ảnh" and _post_body_has_comment_thread_a11y(text):
        return True
    if _is_hashtag_chip(author) and not text:
        return True
    if not author and tl.startswith("nút thích.") and "bình luận" in tl and len(text) < 220:
        return True
    # Real feed rows often include comment-preview a11y under the fold — do not drop those.
    if _post_body_has_comment_thread_a11y(text) and len(text) < 420 and "http" not in tl:
        if "xem thêm" not in tl and "see more" not in tl:
            return True
    return False


def _is_duplicate_short_author_footer_row(
    c: Dict[str, Any], prev_body: Optional[Dict[str, Any]],
) -> bool:
    """Orphan footer-only row: like/reply a11y gives short name ⊆ previous full display name."""
    if not prev_body:
        return False
    if c.get("_type") == "post_stats" or prev_body.get("_type") == "post_stats":
        return False
    t = (c.get("text") or "").strip()
    if t:
        return False
    ca = (c.get("author") or "").strip().lower()
    pa = (prev_body.get("author") or "").strip().lower()
    if not ca or not pa or len(ca) < 6:
        return False
    if ca == pa:
        return False
    return bool(pa.endswith(ca) or ca in pa)


def _is_comment_row_parse_noise(c: Dict[str, Any]) -> bool:
    """Nhiễu UI / parse vỡ rõ ràng — bỏ khỏi output ``parse_fb_comments_from_xml``.

    Hàng chỉ có tên (body rỗng) vẫn **giữ** ở đây để test/corpus đếm thread; lúc lưu DB
    dùng ``_is_junk_parsed_comment_row`` (thêm rule body bắt buộc).
    """
    if c.get("_type") == "post_stats":
        return False
    author_raw = (c.get("author") or "").strip()
    text_raw = (c.get("text") or "").strip()
    author = author_raw.lower()
    text = text_raw.lower()
    combined = f"{author} {text}"
    if author == "đóng":
        return True
    if author in ("xem thêm", "see more"):
        return True
    if "lựa chọn khác cho bài viết" in author or "lựa chọn khác cho bài viết" in text:
        return True
    if "tìm kiếm trong" in author or "tìm kiếm trong" in text:
        return True
    if "công cụ khác cho thành viên" in combined:
        return True
    if "kết quả tìm kiếm" in author or "kết quả tìm kiếm" in text:
        return True
    if "video sound toggle" in author or "video sound toggle" in text:
        return True
    if _RE_SHARES_COUNT_LABEL.match(author):
        return True
    if "open features menu" in text or "use voice typing" in text:
        return True
    if author.startswith("viết bình luận") or text.startswith("viết bình luận"):
        return True
    if author.startswith("write a comment") or text.startswith("write a comment"):
        return True
    if author.startswith("write a public comment") or text.startswith("write a public comment"):
        return True
    if text_raw and _looks_like_comment_timestamp_row(text_raw):
        return True
    if author_raw and _looks_like_comment_timestamp_row(author_raw):
        return True
    if author_raw and _RE_CMT_REACTIONS.match(author_raw.strip()) and not text_raw:
        return True
    if author_raw and author_raw.strip().lower() in {"cảm xúc", "gỡ", "remove"}:
        return True
    if author == "you" and text in ("to", "to.", "tới"):
        return True
    if "mở tìm kiếm tệp" in author or "mở tìm kiếm tệp" in text:
        return True
    if "nhãn dán avatar" in text or ("sticker" in text and "avatar" in text):
        return True
    if "\n" in author_raw or "\n" in text_raw:
        return True
    if len(author_raw) > 72:
        return True
    if "http://" in author_raw or "https://" in author_raw:
        return True
    if (
        author_raw
        and text_raw
        and author == text
        and len(author) < 120
        and (
            "người đóng góp" in author
            or _comment_line_is_badge(author_raw)
            or author in {x.lower() for x in _CMT_EMPTY_BODY_JUNK_AUTHOR}
        )
    ):
        return True
    if not text_raw:
        alo = author_raw.lower()
        if alo in {x.lower() for x in _CMT_EMPTY_BODY_JUNK_AUTHOR}:
            return True
        if "bạn viết gì đi" in alo:
            return True
        norm_a = unicodedata.normalize("NFC", author_raw.strip())
        if _RE_LEAKED_REL_TIME_AS_LABEL.match(norm_a):
            return True
        if (
            author_raw
            and 1 <= len(author_raw) <= 22
            and " " not in author_raw
            and not _comment_line_is_badge(author_raw)
        ):
            return True
    return False


def _is_junk_parsed_comment_row(c: Dict[str, Any]) -> bool:
    """Hàng không nên lưu DB / không nên gộp vào ctx scenario (đủ author + body sạch)."""
    if c.get("_type") == "post_stats":
        return False
    if _is_comment_row_parse_noise(c):
        return True
    if not (c.get("text") or "").strip():
        return True
    return False


def _find_post_time_anchor(cluster: List[Dict[str, Any]]) -> Tuple[int, str]:
    """Return (anchor_index, timestamp_text).

    Nodes with index < anchor are header + body (+ optional image caption);
    index >= anchor are stats / actions. ``timestamp_text`` is empty when FB hides the time row.
    """
    for i, n in enumerate(cluster):
        raw = n["text"].strip()
        if len(raw) > _MAX_TS_ANCHOR_NODE_LEN:
            continue
        if _RE_TS.search(raw):
            return i, raw
    for i, n in enumerate(cluster):
        if _is_post_action_delimiter(n["text"]):
            return i, ""
    return len(cluster), ""


def _parse_bounds(node) -> Optional[Tuple[int, int, int, int]]:
    m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def _normalize_fb_ui_spacing(value: str) -> str:
    """Chuẩn hóa NBSP / narrow NBSP trong chuỗi UI Katana (text / content-desc)."""
    if not value:
        return ""
    s = unicodedata.normalize("NFC", value).replace("\u00a0", " ").replace("\u202f", " ")
    return s.strip()


def _cy(bounds: Tuple[int, int, int, int]) -> int:
    return (bounds[1] + bounds[3]) // 2


def _recycler_item_top_y_sort_key(el) -> Tuple[int, int]:
    """StaggeredGrid / RecyclerView: XML child order often ≠ top-to-bottom on screen.

    Sort by top edge Y (then X) so ``posts[0]`` matches the visually uppermost card
    (e.g. ``_fb_comment_parent_pid`` + first ``Bình luận`` tap).
    """
    b = _parse_bounds(el)
    if not b:
        return (2_147_483_647, 0)
    return (b[1], b[0])


def _infer_screen_size(root) -> Tuple[int, int]:
    """Largest node bounds area ≈ logical screen (for gap thresholds)."""
    best_area = 0
    best_wh = (1080, 2200)
    for node in root.iter():
        b = _parse_bounds(node)
        if not b:
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        a = w * h
        if a > best_area and w >= 320 and h >= 480:
            best_area = a
            best_wh = (w, h)
    return best_wh


def _score_feed_container(el, screen_w: int, screen_h: int) -> float:
    """Prefer tall, wide scroll regions; down-rank short strips (stories/composer chips)."""
    b = _parse_bounds(el)
    if not b:
        return -1.0
    w, h = b[2] - b[0], b[3] - b[1]
    if h < max(120, int(screen_h * 0.11)):
        return -1.0
    cls = el.get("class") or ""
    node_count = len(el.findall(".//node"))
    if node_count < 3:
        return -1.0
    area = float(w * h)
    # Staggered grid is the common group/feed root on Katana.
    boost = 1.25 if "StaggeredGrid" in cls else 1.0
    score = area * math.log(1 + node_count) * boost
    width_ratio = w / float(screen_w or 1)
    if width_ratio < 0.72:
        score *= 0.45
    if h < 220 and w < int(screen_w * 0.92):
        score *= 0.35
    return score


def _pick_feed_container(containers: List[Any], root) -> Any:
    screen_w, screen_h = _infer_screen_size(root)
    ranked = [( _score_feed_container(el, screen_w, screen_h), el) for el in containers]
    ranked.sort(key=lambda t: t[0], reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]
    return max(containers, key=lambda el: len(el.findall("node")))


def _iter_node_text_and_desc(element) -> List[str]:
    out: List[str] = []
    for node in element.iter():
        for key in ("text", "content-desc"):
            v = (node.get(key) or "").strip()
            if v:
                out.append(v)
    return out


def _extract_fb_link_meta(element) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Best-effort real post/group ids from visible strings (share sheets, link previews)."""
    group_id: Optional[str] = None
    post_id: Optional[str] = None
    permalinks: List[str] = []
    for s in _iter_node_text_and_desc(element):
        m = _RE_FB_GROUP_POST.search(s)
        if m:
            group_id, post_id = m.group(1), m.group(2)
            permalinks.append(m.group(0))
            continue
        m = _RE_FB_GROUP_PERM.search(s)
        if m:
            group_id, post_id = m.group(1), m.group(2)
            permalinks.append(m.group(0))
            continue
        m = _RE_FB_POST_SLUG.search(s)
        if m and post_id is None:
            post_id = m.group(1)
            permalinks.append(m.group(0))
        m = _RE_FB_STORY_FBID.search(s)
        if m and post_id is None:
            post_id = m.group(1)
    return post_id, group_id, permalinks


def _resource_id_media_hint(element) -> Optional[str]:
    for node in element.iter():
        rid = (node.get("resource-id") or "").lower()
        if not rid:
            continue
        if _RE_RES_REEL.search(rid):
            return "reel"
        if _RE_RES_VIDEO.search(rid):
            return "video"
    return None


def _structural_post_type_hint(element) -> Optional[str]:
    if _resource_id_media_hint(element) == "reel":
        return "reel"
    if _resource_id_media_hint(element) == "video":
        return "video"
    seen_video = False
    large_image = False
    for node in element.iter():
        cls = node.get("class") or ""
        if cls in _VIDEO_CLASSES:
            seen_video = True
            break
        if "ImageView" in cls:
            b = _parse_bounds(node)
            if b:
                area = (b[2] - b[0]) * (b[3] - b[1])
                if area >= _MIN_IMAGE_AREA_FOR_PHOTO_HINT:
                    large_image = True
    if seen_video:
        return "video"
    if large_image:
        return "photo"
    return None


def _merge_post_type(
    text_type: str,
    structural: Optional[str],
    rid_hint: Optional[str],
    *,
    has_fb_link: bool,
    body_len: int,
) -> str:
    out = text_type
    if rid_hint == "reel" or structural == "reel":
        out = "reel"
    elif rid_hint == "video" or structural == "video":
        if out != "reel":
            out = "video"
    elif structural == "photo" and out == "text":
        out = "photo"
    if has_fb_link and out == "text" and body_len < 56:
        out = "link"
    return out


def _collect_text_nodes(element, toolbar_cutoff_y: int = 200) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for node in element.iter():
        text = _normalize_fb_ui_spacing(node.get("text") or "")
        desc = _normalize_fb_ui_spacing(node.get("content-desc") or "")

        # Trích xuất tên tác giả từ content-desc avatar: "Ảnh đại diện của {NAME}..."
        is_author_hint = False
        desc_lower = desc.lower()
        if desc_lower.startswith(_AUTHOR_PREFIX):
            remainder = desc[len(_AUTHOR_PREFIX):].strip().lstrip(",").strip()
            # Lấy phần trước dấu phẩy đầu tiên (bỏ ", Nút." hoặc phần phụ)
            name_part = remainder.split(",")[0].strip()
            if 2 <= len(name_part) <= 80:
                content = name_part
                is_author_hint = True
            else:
                continue
        else:
            # "nút thích" content-desc có thể chứa số like → dùng desc thay vì bỏ
            desc_lower_full = desc.lower()
            if not text and desc_lower_full.startswith("nút thích"):
                # Bỏ qua, không có số
                continue
            # Ưu tiên content-desc nếu chứa số stats và text rỗng/ngắn
            if not text and desc and re.search(r"\d", desc):
                content = desc
            else:
                content = text if text else desc
            if not content:
                continue

        bounds = _parse_bounds(node)
        if not bounds:
            continue
        if bounds[3] < toolbar_cutoff_y:
            continue
        if bounds[0] == bounds[2] or bounds[1] == bounds[3]:
            continue
        nodes.append({
            "text":        content,
            "bounds":      bounds,
            "cy":          _cy(bounds),
            "resource_id": node.get("resource-id") or "",
            "is_author_hint": is_author_hint,
        })
    nodes.sort(key=lambda n: n["cy"])
    return nodes


def _is_ad_container(element) -> bool:
    for node in element.iter():
        if (node.get("resource-id") or "") in _AD_RESOURCE_IDS:
            return True
    return False


def _extract_media_artifacts(element) -> List[Dict[str, Any]]:
    """Collect multi-photo carousel affordances from one feed row subtree.

    Each entry is one tappable tile; ``bounds`` are screen coords for linking
    to screenshots / tap replay. Same element subtree as ``_extract_post`` input.
    """
    found: List[Dict[str, Any]] = []
    for node in element.iter():
        desc = (node.get("content-desc") or "").strip()
        text = (node.get("text") or "").strip()
        label = desc or text
        if not label:
            continue
        if desc.lower().startswith(_AUTHOR_PREFIX):
            continue
        m = _RE_FB_CAROUSEL.search(label)
        if not m:
            continue
        slot, total = int(m.group(1)), int(m.group(2))
        b = _parse_bounds(node)
        found.append({
            "kind": "carousel_photo",
            "label": label,
            "slot": slot,
            "total": total,
            "bounds": [b[0], b[1], b[2], b[3]] if b else None,
            "android_class": node.get("class") or "",
        })
    found.sort(key=lambda x: (x["slot"], (x["bounds"] or [0, 0, 0, 0])[1]))
    return found


def _extract_post(
    cluster: List[Dict[str, Any]],
    source_index: int,
    *,
    structural_type_hint: Optional[str] = None,
    resource_id_media_hint: Optional[str] = None,
    fb_post_id: Optional[str] = None,
    fb_group_id: Optional[str] = None,
    permalink_candidates: Optional[List[str]] = None,
    feed_item_index: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    if not cluster:
        return None
    anchor_idx, timestamp = _find_post_time_anchor(cluster)

    all_lower = " ".join(n["text"].lower() for n in cluster)

    if _RE_REEL_TYPE.search(all_lower):
        post_type: str = "reel"
    elif _RE_VIDEO_TYPE.search(all_lower):
        post_type = "video"
    elif _RE_LINK_TYPE.search(all_lower):
        post_type = "link"
    elif _RE_POST_RESHARE_HEADER.search(all_lower) and (fb_post_id or permalink_candidates):
        post_type = "link"
    else:
        post_type = "text"

    # Ưu tiên node có is_author_hint (từ content-desc avatar) làm author
    author: Optional[str] = next(
        (n["text"] for n in cluster if n.get("is_author_hint") and n["text"]),
        None,
    )
    body_parts: List[str] = []
    reactions = comments = shares = views = None
    image_desc: Optional[str] = None
    comment_preview_parts: List[str] = []
    stats_seen: bool = False

    for i, node in enumerate(cluster):
        t = node["text"].strip()
        t_lower = t.lower()

        if i == anchor_idx:
            continue
        if node.get("is_author_hint"):
            continue  # đã xử lý ở trên
        # "Bình luận" / "Comment" are in _NOISE_TEXTS but are post-action delimiters after anchor.
        if len(t) <= 1:
            continue
        if _is_noise_text(t) and not (
            i > anchor_idx and t_lower in ("bình luận", "comment")
        ):
            continue

        # Album tiles (VN: "Ảnh 1/3, mở rộng ảnh") — never merge into body text.
        if _RE_FB_CAROUSEL.search(t):
            if image_desc is None:
                image_desc = t
            continue

        if (i < anchor_idx and author is None and 2 <= len(t) <= 50
                and "•" not in t and "chia sẻ với" not in t_lower
                and "http" not in t_lower and "www." not in t_lower
                and not _is_hashtag_chip(t)):
            author = t
            continue

        # Include i==0: single-card post views often expose one huge ViewGroup text
        # as the only pre-anchor node (no timestamp row → anchor_idx == len(cluster)).
        if i < anchor_idx and t != author:
            if image_desc is None and _RE_IMAGE_TYPE.match(t_lower) and 8 < len(t) < 300:
                image_desc = t
                continue
            body_parts.append(t)
            continue

        if i > anchor_idx:
            if image_desc is None and _RE_IMAGE_TYPE.match(t_lower) and 8 < len(t) < 300:
                image_desc = t
                continue

            # Katana often has no combined "1K · 5 bình luận" line — only a11y button rows.
            # Stop appending caption once we hit Thích / Bình luận / Chia sẻ on the *post*.
            if _is_post_action_delimiter(t):
                stats_seen = True
                continue

            stats = _parse_stats(t)
            matched_stat = False
            if stats["reactions"] is not None and reactions is None:
                reactions = stats["reactions"]
                matched_stat = True
            if stats["comments"] is not None and comments is None:
                comments = stats["comments"]
                matched_stat = True
            if stats["shares"] is not None and shares is None:
                shares = stats["shares"]
                matched_stat = True
            if stats["views"] is not None and views is None:
                views = stats["views"]
                matched_stat = True

            if matched_stat:
                stats_seen = True
            elif not _is_noise_text(t):
                if stats_seen:
                    if _is_fb_comment_thread_chrome_row(t):
                        continue
                    comment_preview_parts.append(t)
                else:
                    body_parts.append(t)

    comment_preview = " ".join(comment_preview_parts).strip() or None
    body = " ".join(body_parts).strip()
    if body:
        b = body.lower()
        if any(b.startswith(prefix) for prefix in _NOISE_PREFIXES):
            body = ""
        if any(token in b for token in _NOISE_CONTAINS):
            body = ""
        if "chia sẻ với: nhóm công khai" in b and len(body) < 60:
            body = ""

    if not author and not body:
        return None

    if image_desc and post_type == "text":
        post_type = "photo"

    permalinks = list(permalink_candidates or [])
    has_fb_link = bool(fb_post_id or permalinks)
    post_type = _merge_post_type(
        post_type,
        structural_type_hint,
        resource_id_media_hint,
        has_fb_link=has_fb_link,
        body_len=len(body),
    )

    # _pid: 16-char MD5 of author+body[:120], mirrors _compute_post_id_from_nodes.
    # Used to cross-reference this feed post with its comment-view header in the executor.
    _pid_raw = f"{author or ''}\x00{body[:120]}"
    _pid = hashlib.md5(_pid_raw.encode()).hexdigest()[:16]

    # Stable logical post identity for merge/dedup across preview → expanded versions.
    # Keep it resilient to body growth by using normalized prefix, not full text.
    _stable_prefix = unicodedata.normalize("NFC", re.sub(r"\s+", " ", body.lower()).strip())
    _stable_prefix = _stable_prefix.replace("…", "").replace("...", "")
    for _mk in _TRUNCATION_MARKERS:
        _stable_prefix = _stable_prefix.replace(_mk, "")
    _stable_prefix = _stable_prefix.strip()[:100]
    # Do not include timestamp in stable id: timestamp labels can vary ("1 giờ", "59 phút")
    # across captures for the same logical post and would split dedup keys.
    _sid_author = unicodedata.normalize("NFC", (author or "").strip().lower())
    _sid_img = unicodedata.normalize("NFC", (image_desc or "").strip().lower())[:40]
    _sid_raw = f"{_sid_author}\x00{_stable_prefix}\x00{_sid_img}"
    stable_post_id = hashlib.sha1(_sid_raw.encode("utf-8")).hexdigest()

    # Stable key for dedupe/linking: stronger than text-only hash.
    _pk_raw = f"{author or ''}\x00{body}\x00{image_desc or ''}\x00{comment_preview or ''}"
    post_key = hashlib.sha1(_pk_raw.encode("utf-8")).hexdigest()

    out: Dict[str, Any] = {
        "author":          author or "",
        "text":            body,
        "timestamp":       timestamp,
        "reactions":       reactions,
        "comments":        comments,
        "shares":          shares,
        "views":           views,
        "source_index":    source_index,
        "post_type":       post_type,
        "image_desc":      image_desc,
        "comment_preview": comment_preview,
        "_pid":            _pid,
        "stable_post_id":  stable_post_id,
        "post_key":        post_key,
        "fb_post_id":      fb_post_id,
        "fb_group_id":     fb_group_id,
        "permalink_candidates": permalinks,
    }
    if feed_item_index is not None:
        out["feed_item_index"] = feed_item_index
    return out


def _hierarchy_is_fb_comment_sheet(root) -> bool:
    """Thread / reply sheet: nút ``Đóng`` + RecyclerView không full màn — không phải feed bài viết."""
    has_dong = False
    for node in root.iter():
        if (node.get("package") or "") != "com.facebook.katana":
            continue
        desc = (node.get("content-desc") or "").strip()
        cls = node.get("class") or ""
        if desc == "Đóng" and "Button" in cls:
            has_dong = True
            break
    if not has_dong:
        return False
    containers = root.xpath(_XPATH_RECYCLER) or root.xpath(_XPATH_LIST)
    if not containers:
        return False
    feed = _pick_feed_container(containers, root)
    b = _parse_bounds(feed)
    if not b:
        return False
    _, _, _, y2 = b
    _, screen_h = _infer_screen_size(root)
    if screen_h < 400:
        return False
    return y2 <= int(screen_h * 0.78)


def _feed_comment_y_max(root, action_btn_y_mid: Optional[int]) -> Optional[int]:
    """Bottom Y của đúng một card feed chứa hàng Thích/Bình luận/Chia sẻ.

    Tránh parse cả bài viết *kế tiếp* (timestamp, caption, …) như comment khi
    RecyclerView có nhiều item trên cùng màn. Thread / comment sheet → None.
    """
    if action_btn_y_mid is None:
        return None
    if _hierarchy_is_fb_comment_sheet(root):
        return None
    containers = root.xpath(_XPATH_RECYCLER) or root.xpath(_XPATH_LIST)
    if not containers:
        return None
    feed = _pick_feed_container(containers, root)
    for child in feed.findall("node"):
        b = _parse_bounds(child)
        if b and b[1] <= action_btn_y_mid <= b[3]:
            return b[3]
    return None


def _extract_posts_from_recycler(root, source_index: int) -> Optional[List[Dict[str, Any]]]:
    containers = root.xpath(_XPATH_RECYCLER) or root.xpath(_XPATH_LIST)
    if not containers:
        return None
    if _hierarchy_is_fb_comment_sheet(root):
        return []
    feed = _pick_feed_container(containers, root)
    candidates = feed.findall("node")
    if not candidates:
        return None
    candidates = sorted(candidates, key=_recycler_item_top_y_sort_key)
    posts: List[Dict[str, Any]] = []
    for feed_item_index, candidate in enumerate(candidates):
        if _is_ad_container(candidate):
            continue
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
        media_artifacts = _extract_media_artifacts(candidate)
        post = _extract_post(
            nodes,
            source_index,
            structural_type_hint=_structural_post_type_hint(candidate),
            resource_id_media_hint=_resource_id_media_hint(candidate),
            fb_post_id=fb_pid,
            fb_group_id=fb_gid,
            permalink_candidates=perms,
            feed_item_index=feed_item_index,
        )
        if post:
            _maybe_fix_merged_feed_caption(post)
            _refresh_post_derived_hashes(post)
            if media_artifacts:
                post["media_artifacts"] = media_artifacts
                if post.get("post_type") == "text":
                    post["post_type"] = "photo"
            if _is_junk_recycler_post(post):
                continue
            posts.append(post)
    return posts


def _should_merge_post_nodes_despite_vertical_gap(
    prev: Dict[str, Any],
    nxt: Dict[str, Any],
    gap: float,
    gap_threshold: float,
) -> bool:
    """Hai node text dài cùng lề — hay là hai đoạn một bài bị layout tách xa dọc."""
    if gap <= gap_threshold:
        return False
    max_relax = min(540, int(gap_threshold * 2.4))
    if gap > max_relax:
        return False
    pt = prev["text"].strip()
    nt = nxt["text"].strip()
    tl = nt.lower()
    if len(pt) < 32 or len(nt) < 24:
        return False
    # Dòng tên ngắn (một token) — thường là đầu bài kế, không gộp
    if len(nt) <= 26 and " " not in nt and "http" not in tl:
        return False
    # Hàng giờ tương đối ngắn — ranh giới bài / stats
    if len(nt) <= 44 and _RE_TS.search(nt) and "http" not in tl:
        return False
    px, nx = prev["bounds"][0], nxt["bounds"][0]
    if abs(px - nx) > 52:
        return False
    plow = pt.lower()
    if any(plow.startswith(p) for p in _NOISE_PREFIXES):
        return False
    return True


def _cluster_into_posts(
    nodes: List[Dict[str, Any]],
    *,
    screen_height: int = 2200,
) -> List[List[Dict[str, Any]]]:
    if not nodes:
        return []
    # Scale with viewport; clamp — tăng nhẹ để ít tách đoạn body dài (FB tách nhiều ViewGroup).
    GAP_THRESHOLD = max(120, min(290, int(screen_height * 0.076)))
    ts_gap_split = max(18, GAP_THRESHOLD // 5)
    clusters: List[List[Dict]] = []
    current: List[Dict] = [nodes[0]]
    prev_cy = nodes[0]["cy"]
    current_has_ts = bool(_RE_TS.search(nodes[0]["text"]))
    for node in nodes[1:]:
        gap = node["cy"] - prev_cy
        is_ts = bool(_RE_TS.search(node["text"]))
        prev_node = current[-1]
        merge_despite_gap = gap > GAP_THRESHOLD and _should_merge_post_nodes_despite_vertical_gap(
            prev_node, node, gap, GAP_THRESHOLD,
        )
        if merge_despite_gap:
            current.append(node)
            if is_ts:
                current_has_ts = True
            prev_cy = node["cy"]
            continue
        if gap > GAP_THRESHOLD or (current_has_ts and is_ts and gap > ts_gap_split):
            clusters.append(current)
            current = [node]
            current_has_ts = is_ts
        else:
            current.append(node)
            if is_ts:
                current_has_ts = True
        prev_cy = node["cy"]
    if current:
        clusters.append(current)
    return clusters


def _parse_xml(xml: str) -> Optional[Any]:
    try:
        raw = xml.encode("utf-8") if isinstance(xml, str) else xml
        return _lxml.fromstring(raw, parser=_LXML_PARSER)
    except Exception as exc:
        log.warning("fb_extract: XML parse error: %s", exc)
        return None


def parse_fb_posts_from_xml(xml: str, source_index: int = 0) -> List[Dict[str, Any]]:
    """Parse UIAutomator2 hierarchy XML → list of post dicts."""
    root = _parse_xml(xml)
    if root is None:
        return []
    _, screen_h = _infer_screen_size(root)
    posts = _extract_posts_from_recycler(root, source_index)
    if posts is not None:
        if posts:
            return posts
        # Recycler trả về []: thread/sheet (cố ý) hoặc mọi item bị lọc — chỉ thread thì không fallback.
        if _hierarchy_is_fb_comment_sheet(root):
            return []
    nodes = _collect_text_nodes(root)
    clusters = _cluster_into_posts(nodes, screen_height=screen_h)
    result: List[Dict[str, Any]] = []
    for cluster in clusters:
        post = _extract_post(cluster, source_index)
        if post:
            _maybe_fix_merged_feed_caption(post)
            _refresh_post_derived_hashes(post)
            if not _is_junk_recycler_post(post):
                result.append(post)
    return result


def _dedup(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate feed posts while preferring the richer/fuller version.

    Key keeps compatibility with historical behavior:
    same author + timestamp + text-prefix[:60] is considered the same post.

    Important: when both truncated and expanded versions appear, keep the one
    with longer body and richer metadata (stats/image/comment preview).
    """
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []

    def _quality(post: Dict[str, Any]) -> Tuple[int, int, int]:
        text = str(post.get("text") or "")
        stats_count = sum(
            1
            for k in ("reactions", "comments", "shares", "views", "image_desc", "comment_preview")
            if post.get(k)
        )
        unresolved = int(any(mk in text.lower() for mk in _TRUNCATION_MARKERS))
        # Prefer resolved/non-truncated text first, then length, then richer metadata.
        return (-unresolved, len(text), stats_count)

    def _norm_text(value: str) -> str:
        t = unicodedata.normalize("NFC", (value or "").lower())
        t = re.sub(r"\s+", " ", t).strip()
        for mk in _TRUNCATION_MARKERS:
            t = t.replace(mk, "")
        return re.sub(r"\s+", " ", t).strip()

    def _likely_same_logical_post(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        ta = _norm_text(str(a.get("text") or ""))
        tb = _norm_text(str(b.get("text") or ""))
        if not ta or not tb:
            return True
        # Truncated/expanded variants usually keep one body as prefix of the other.
        return ta.startswith(tb) or tb.startswith(ta)

    for p in posts:
        stable_post_id = str(p.get("stable_post_id") or "")
        timestamp = str(p.get("timestamp") or "")
        if stable_post_id:
            key = ("sid", stable_post_id)
        else:
            # Backward compatibility fallback for old records without stable_post_id.
            author = str(p.get("author") or "")
            text = str(p.get("text") or "")
            key = ("legacy", f"{author}\x00{timestamp}\x00{text[:60]}")

        existing = by_key.get(key)
        if existing is None:
            by_key[key] = p
            order.append(key)
            continue

        # Guard against stable-id collisions (same sid but clearly different bodies).
        if key[0] == "sid" and not _likely_same_logical_post(existing, p):
            collision_key = ("sid-collision", f"{stable_post_id}\x00{p.get('post_key') or p.get('_pid') or len(order)}")
            if collision_key not in by_key:
                by_key[collision_key] = p
                order.append(collision_key)
            continue

        if _quality(p) > _quality(existing):
            by_key[key] = p

    return [by_key[k] for k in order]


# ── Comment-like button patterns (from real UIAutomator XML) ─────────────────
# "Nút Thích bình luận của Đỗ. Nhấn đúp..."  → author short name = "Đỗ"
# "Trả lời bình luận của Tuấn, nút. ..."     → author short name = "Tuấn"
_RE_CMT_LIKE_BTN = re.compile(
    r"^Nút Thích bình luận của (.+?)\.", re.IGNORECASE
)
_RE_CMT_REPLY_BTN = re.compile(
    r"^Trả lời bình luận của (.+?),", re.IGNORECASE
)
# "N cảm xúc" → comment reaction count (different from post reactions)
_RE_CMT_REACTIONS = re.compile(r"^(\d[\d.,]*[KMkm]?)\s+cảm xúc$", re.IGNORECASE)
_RE_CMT_REACTIONS_EN = re.compile(r"^(\d[\d.,]*[KMkm]?)\s+reactions?\s*$", re.IGNORECASE)


def _is_comment_reaction_count_row(text: str) -> bool:
    """Right-aligned chip ``N cảm xúc`` / ``N reactions`` (x often past comment_x_max)."""
    t = (text or "").strip()
    return bool(_RE_CMT_REACTIONS.match(t) or _RE_CMT_REACTIONS_EN.match(t))


# Timestamp or post-share suffix that can appear in comment timestamp field
_RE_CMT_TS_SHARE = re.compile(r"•\s*Chia sẻ với.*$", re.IGNORECASE)

# Noise specific to comment area
_CMT_NOISE_TEXTS = frozenset({
    "thích", "trả lời", "like", "reply",
    "xem thêm câu trả lời", "ẩn câu trả lời",
    "theo dõi", "· theo dõi",
    "menu", "delete",
    "tìm kiếm",
    "space",
})

# Author-only rows sau parse (keyboard, toolbar, chip) — không phải comment.
_CMT_EMPTY_BODY_JUNK_AUTHOR = frozenset({
    "menu",
    "delete",
    "tìm kiếm",
    "space",
    "người đóng góp nổi bật",
    "người đóng góp đang lên",
    "người đóng góp nhiều nhất",
    "cảm xúc",
    "gỡ",
    "video sound toggle",
    "openclaw vn",
    "tham gia",
    "truy cập",
    "tác giả",
    "you",
    "to",
})

# Dòng giờ lọt làm "author" khi cluster vỡ.
_RE_LEAKED_REL_TIME_AS_LABEL = re.compile(
    r"^\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm)\s*(?:trước)?$",
    re.IGNORECASE,
)

# Short profile / engagement labels next to names in comment UI (VN FB).
_CMT_BADGE_LABELS = frozenset({
    "quan tâm",
    "xin thông tin",
    "thành viên mới",
    "người tạo bài viết",
    "quản trị viên",
    "người kiểm duyệt",
    "chuyên gia được xác minh",
    "top fan",
    "người hay bình luận",
    "tác giả",
    "author",
    "moderator",
    "admin",
    "founding member",
    "visual storyteller",
    "đã xác minh",
    "verified",
    "cộng tác viên",
    "collaborator",
    "bạn bè",
    "friend",
    "được mời",
    "người ảnh hưởng",
    "chuyên gia",
    "fan cứng",
    "siêu fan",
    "super fan",
    "pre-broadcast contributor",
    "người hâm mộ",
    "subscriber",
    "đăng ký theo dõi",
    "fan cuồng",
    "người hay tương tác",
    "rising creator",
})


def _comment_line_is_badge(text: str) -> bool:
    """VN/EN badge chip under commenter name (exact or contains a long known label)."""
    tl = text.strip().lower()
    if len(tl) < 2 or len(tl) > 72:
        return False
    if tl in _CMT_BADGE_LABELS:
        return True
    # Substring only for multi-char labels (avoid "admin" ⊂ unrelated short text).
    if any(b in tl for b in _CMT_BADGE_LABELS if len(b) >= 10):
        return True
    # Cụm chip dạng "Top …" / "Visual …" (FB đôi khi ghép nhãn dài).
    if tl.startswith("top ") and "fan" in tl:
        return True
    if tl.startswith("siêu fan") or tl.startswith("fan cứng"):
        return True
    if tl.startswith("fan cuồng"):
        return True
    return False


_RE_COMMENT_NAME_DOT_SUFFIX = re.compile(r"^(.{2,60}?)\s*[•·]\s*(.+)$")


def _refine_comment_author_from_cluster(
    cluster: List[Dict[str, Any]], author: Optional[str],
) -> Optional[str]:
    """Nút Thích/Trả lời đôi khi có họ tên đầy đủ hơn dòng tên bị cắt (vd. Van → Van Nguyen)."""
    if not author:
        return author
    au = unicodedata.normalize("NFC", author.strip())
    au_l = au.lower()
    best = ""
    for node in cluster:
        t = node["text"].strip()
        m = _RE_CMT_LIKE_BTN.match(t)
        if m:
            cand = m.group(1).strip()
            if len(cand) > len(best):
                best = cand
        m = _RE_CMT_REPLY_BTN.match(t)
        if m:
            cand = m.group(1).strip()
            if len(cand) > len(best):
                best = cand
    if not best:
        return author
    best = unicodedata.normalize("NFC", best)
    bl = best.lower()
    if len(best) > len(au) and bl.startswith(au_l):
        return best
    return author


def _is_cmt_chrome_search_or_post_menu_text(text: str) -> bool:
    """Chuỗi từ thanh FB (tìm kiếm, menu bài, thăm dò…) — không phải nội dung comment."""
    tl = text.strip().lower()
    if not tl:
        return False
    if "tìm kiếm trong" in tl:
        return True
    if "công cụ khác cho thành viên" in tl:
        return True
    if "lựa chọn khác cho bài viết" in tl:
        return True
    if tl.startswith("kết quả tìm kiếm"):
        return True
    if "xem toàn bộ lịch sử tìm kiếm" in tl:
        return True
    if "xem tất cả những người bạn có thể biết" in tl:
        return True
    if "thăm dò ý kiến" in tl and "lựa chọn khác" in tl:
        return True
    if "bạn viết gì đi" in tl:
        return True
    if "· truy cập" in tl or "• truy cập" in tl:
        return True
    if tl == "truy cập":
        return True
    return False


def _is_cmt_noise(text: str) -> bool:
    t = text.strip()
    tl = t.lower()
    if not tl or tl in _CMT_NOISE_TEXTS:
        return True
    if _is_cmt_chrome_search_or_post_menu_text(t):
        return True
    if _RE_SHARES_COUNT_LABEL.match(t.strip()):
        return True
    if tl == "đóng":
        return True
    if "đang hiển thị" in tl and "bình luận" in tl:
        return True
    if tl.startswith("nút thích bình luận"):
        return True
    if tl.startswith("trả lời bình luận"):
        return True
    if tl == "tham gia":
        return True
    if tl.startswith("viết bình luận"):
        return True
    if tl.startswith("write a comment") or tl.startswith("write public comment"):
        return True
    if tl.startswith("write a public comment"):
        return True
    if tl.startswith("add a comment"):
        return True
    return False


def _looks_like_comment_timestamp_row(text: str) -> bool:
    """Dòng giờ / chia sẻ của bài viết — không gộp vào cluster comment."""
    t = text.strip()
    if len(t) > 96:
        return False
    tl = t.lower()
    if "chia sẻ với" in tl:
        return True
    if ("•" in t or "·" in t) and _RE_TS.search(t):
        return True
    return False


def _is_comment_image_placeholder_text(text: str) -> bool:
    """Image-only comment row (no caption in a11y tree)."""
    tl = (text or "").strip().lower()
    return tl in ("ảnh", "photo", "image", "hình ảnh", "picture")


def _is_compact_comment_action_label(text: str, bounds: List[int]) -> bool:
    """Short ``Thích`` / ``Trả lời`` button text duplicated under long a11y ViewGroup."""
    t = (text or "").strip().lower()
    if t not in ("thích", "trả lời", "like", "reply"):
        return False
    if len(bounds) < 4:
        return False
    return (int(bounds[2]) - int(bounds[0])) < 220


def _is_comment_left_avatar_name_strip(n: Dict[str, Any]) -> bool:
    """Commenter name from left avatar tile (x≈40, width ~140). Excludes wide reaction rows like ``167``."""
    b = n.get("bounds") or []
    if len(b) < 4:
        return False
    x0, _, x1, _ = int(b[0]), int(b[1]), int(b[2]), int(b[3])
    if x0 < 28 or x0 >= 150:
        return False
    if x1 > 230:
        return False
    t = (n.get("text") or "").strip()
    if not (2 <= len(t) <= 90):
        return False
    if _comment_line_is_badge(t):
        return False
    if _is_comment_image_placeholder_text(t):
        return False
    if _looks_like_comment_timestamp_row(t):
        return False
    if _is_cmt_noise(t):
        return False
    tl = t.lower()
    if tl.startswith("nút ") or "bình luận của" in tl:
        return False
    if re.search(r"\d", t) and len(t) <= 6 and " " not in t:
        return False
    return True


def _should_merge_split_comment_nodes(
    prev: Dict[str, Any], nxt: Dict[str, Any], gap: float,
) -> bool:
    """Gộp hai node liên tiếp bị FB tách theo chiều dọc (tên/badge/body, hoặc body nhiều đoạn)."""
    pt = prev["text"].strip()
    nt = nxt["text"].strip()
    if not pt or not nt:
        return False
    pl, nl = len(pt), len(nt)
    px, nx = prev["bounds"][0], nxt["bounds"][0]

    # Large vertical gap: image-only tile (a11y text "Ảnh") under badge or name row.
    if _comment_line_is_badge(pt) and _is_comment_image_placeholder_text(nt) and gap <= 1400:
        return True
    if (
        2 <= pl <= 100
        and not _comment_line_is_badge(pt)
        and _is_comment_image_placeholder_text(nt)
        and gap < 1400
    ):
        return True

    # Image tile then footer rows (timestamp / like) — still same comment, gap often 400–900.
    if _is_comment_image_placeholder_text(pt) and gap < 900:
        if len(nt) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(nt):
            return True
        if _looks_like_comment_timestamp_row(nt):
            return True
        if _RE_CMT_LIKE_BTN.match(nt) or _RE_CMT_REPLY_BTN.match(nt):
            return True

    if gap <= 80 or gap > 720:
        return False
    if abs(px - nx) > 120:
        # Name on left avatar column (x<150) + badge row in main column are far apart horizontally.
        if not (
            2 <= pl <= 100
            and not _comment_line_is_badge(pt)
            and _comment_line_is_badge(nt)
            and int(prev["bounds"][0]) < 150
        ):
            return False

    if _looks_like_comment_timestamp_row(pt) or _looks_like_comment_timestamp_row(nt):
        return False
    if _RE_CMT_LIKE_BTN.match(nt) or _RE_CMT_REPLY_BTN.match(nt):
        return False
    if _is_cmt_noise(nt):
        return False

    plow = pt.lower()
    if "http" in plow or "www." in plow:
        return False
    if plow.startswith("nút ") or plow.startswith("trả lời"):
        return False

    # Tên ngắn + badge (chip dưới tên)
    if 2 <= pl <= 100 and _comment_line_is_badge(nt):
        return True

    # Tên / avatar label + badge phía dưới (FB tách dọc)
    if 2 <= pl <= 100 and not _comment_line_is_badge(pt) and _comment_line_is_badge(nt) and gap < 420:
        return True

    # Badge + phần nội dung
    if _comment_line_is_badge(pt) and nl >= 12 and not _comment_line_is_badge(nt):
        return True

    # Tên + body (nới: body ngắn hơn, khe dọc lớn hơn)
    if 2 <= pl <= 100:
        if "•" in pt and pl > 40 and "chia sẻ" not in plow:
            return False
        min_nl = 12 if (" " in nt or nl >= 18) else 22
        if nl >= min_nl:
            if nl < 30 and " " not in nt:
                return False
            return True

    # Hai khối body dài liền nhau (FB tách ViewGroup)
    if pl >= 28 and nl >= 28 and gap <= 300:
        if _RE_CMT_LIKE_BTN.match(pt) or _RE_CMT_REPLY_BTN.match(pt):
            return False
        if " " not in nt and nl < 45:
            return False
        return True

    return False


def _cluster_into_comments(nodes: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Cluster comment text-nodes into per-comment groups.

    Strategy:
    - Each comment starts with an author node (short text, x≥180).
    - A "Nút Thích bình luận của X." desc-node marks the boundary AFTER a comment.
    - Gap > 80px starts a new cluster unless the next node looks like the body
      for the previous short name row (FB splits name / body vertically).
    - After the like row, Katana often emits Trả lời + ``N cảm xúc`` on the same band;
      keep them in the same cluster so reaction counts parse into ``likes``.
    """
    if not nodes:
        return []
    GAP = 80
    clusters: List[List[Dict]] = []
    current: List[Dict] = [nodes[0]]
    prev_cy = nodes[0]["cy"]
    pending_footer = False

    def _inline_comment_footer_row(text: str, footer_gap: float) -> bool:
        tt = text.strip()
        if footer_gap >= 200:
            return False
        if _RE_CMT_REPLY_BTN.match(tt):
            return True
        if _is_comment_reaction_count_row(tt):
            return True
        if len(tt) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(tt):
            return True
        return False

    for node in nodes[1:]:
        gap = node["cy"] - prev_cy
        t = node["text"].strip()
        is_end_marker = bool(_RE_CMT_LIKE_BTN.match(t))

        if pending_footer:
            if _inline_comment_footer_row(t, gap):
                current.append(node)
                prev_cy = node["cy"]
                continue
            clusters.append(current)
            current = [node]
            prev_cy = node["cy"]
            pending_footer = False
            continue

        merge_name_body = (
            not is_end_marker
            and gap > GAP
            and bool(current)
            and _should_merge_split_comment_nodes(current[-1], node, gap)
        )
        if merge_name_body:
            current.append(node)
            prev_cy = node["cy"]
            continue
        if gap > GAP or is_end_marker:
            if is_end_marker:
                current.append(node)
                pending_footer = True
                prev_cy = node["cy"]
                continue
            if current:
                clusters.append(current)
            current = [node]
        else:
            current.append(node)
        prev_cy = node["cy"]

    if current:
        clusters.append(current)
    return clusters


def _extract_comment(
    cluster: List[Dict[str, Any]],
    parent_post_id: Optional[str] = None,
    cluster_min_x: int = 150,
) -> Optional[Dict[str, Any]]:
    """Extract one comment from a text-node cluster.

    Based on observed Facebook feed XML:
    - Author:    first short text (len 2–80), hoặc ghép ``Tên • badge`` / ``Tên • 5 giờ`` một node
    - Badges:    chip dưới tên (danh hiệu) hoặc phần sau dấu • nếu khớp nhãn đã biết
    - Body:      các text node còn lại
    - Timestamp: _RE_TS; chuẩn hóa tên từ nút Thích/Trả lời nếu dài hơn và là tiền tố của tên hiển thị
    - Likes:     "N cảm xúc" hoặc author từ "Nút Thích bình luận của X."
    """
    author: Optional[str] = None
    badges: List[str] = []
    body_parts: List[str] = []
    timestamp: Optional[str] = None
    likes: Optional[str] = None
    pending_badges: List[str] = []

    def _flush_pending_badges() -> None:
        nonlocal pending_badges
        if pending_badges:
            badges.extend(pending_badges)
            pending_badges = []

    for node in cluster:
        t = node["text"].strip()
        if not t or len(t) <= 1:
            continue

        # Extract author name from like-button desc
        m = _RE_CMT_LIKE_BTN.match(t)
        if m:
            if author is None:
                author = m.group(1).strip()
            _flush_pending_badges()
            continue

        # Extract author from reply-button desc (secondary fallback)
        m = _RE_CMT_REPLY_BTN.match(t)
        if m:
            if author is None:
                author = m.group(1).strip()
            _flush_pending_badges()
            continue

        # Skip other noise
        if _is_cmt_noise(t):
            continue

        # "N cảm xúc" / "N reactions" → comment reaction count (stored as likes + reactions)
        m = _RE_CMT_REACTIONS.match(t) or _RE_CMT_REACTIONS_EN.match(t)
        if m:
            likes = m.group(1)
            continue

        # Image-only comment (large ImageView a11y label)
        if _is_comment_image_placeholder_text(t):
            if not any(p.strip() == "[image]" for p in body_parts):
                body_parts.append("[image]")
            continue

        # Badge rows can appear above the display name in the XML order (OP / thread)
        if author is None and _comment_line_is_badge(t):
            pending_badges.append(t.strip())
            continue

        # Avatar content-desc prefix → name-only node
        if author is None and node.get("is_author_hint"):
            if 2 <= len(t) <= 90 and not _comment_line_is_badge(t):
                author = t
                _flush_pending_badges()
                continue

        # Một node: "Tên • Quan tâm" / "Tên • 5 giờ" — trước nhánh timestamp (cả dòng có thể match _RE_TS)
        m_dot = _RE_COMMENT_NAME_DOT_SUFFIX.match(t.strip())
        if author is None and m_dot:
            left, right = m_dot.group(1).strip(), m_dot.group(2).strip()
            if 2 <= len(left) <= 60:
                if _comment_line_is_badge(right):
                    author = left
                    badges.append(right.strip())
                    _flush_pending_badges()
                    continue
                if len(right) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(right):
                    author = left
                    clean_r = _RE_CMT_TS_SHARE.sub("", right).strip()
                    if timestamp is None:
                        timestamp = clean_r if clean_r else right
                    _flush_pending_badges()
                    continue

        # Timestamp (short nodes only — same false-positive as post body)
        if len(t) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(t):
            # Strip "•Chia sẻ với: Nhóm công khai" suffix (appears on post timestamps leaking in)
            clean = _RE_CMT_TS_SHARE.sub("", t).strip()
            if timestamp is None:
                timestamp = clean if clean else t
            continue

        # Author: first short text that hasn't been assigned yet
        if author is None and 2 <= len(t) <= 80 and "·" not in t and "•" not in t and not _is_hashtag_chip(t):
            author = t
            _flush_pending_badges()
            continue

        # Badge line(s) between author row and body (VN/EN UI)
        if author is not None and _comment_line_is_badge(t):
            badges.append(t.strip())
            continue

        # Duplicate display-name row (avatar + inline name chip)
        if author and unicodedata.normalize("NFC", t).lower() == unicodedata.normalize("NFC", author).lower():
            continue

        # Everything else = body
        body_parts.append(t)

    if author and pending_badges:
        badges.extend(pending_badges)

    text = " ".join(body_parts).strip()
    author = _refine_comment_author_from_cluster(cluster, author)
    if not author and not text:
        return None

    # Stable key for dedup across retries/reruns while still separating by parent post.
    norm_author = unicodedata.normalize("NFC", (author or "").strip().lower())
    norm_text = unicodedata.normalize("NFC", text.strip().lower())
    norm_parent = unicodedata.normalize("NFC", (parent_post_id or "").strip().lower())
    comment_key = hashlib.sha1(f"{norm_parent}\x00{norm_author}\x00{norm_text}".encode("utf-8")).hexdigest()

    # indent_level: 0 = top-level comment, 1 = reply (indented x≥220), 2 = deeply nested (x≥280)
    indent_level = 0
    if cluster_min_x >= 280:
        indent_level = 2
    elif cluster_min_x >= 220:
        indent_level = 1

    out: Dict[str, Any] = {
        "author":         author or "",
        "text":           text,
        "timestamp":      timestamp,
        "likes":          likes,
        "parent_post_id": parent_post_id,
        "indent_level":   indent_level,
        "comment_key":    comment_key,
    }
    if likes:
        out["reactions"] = likes
    if badges:
        seen_b: set[str] = set()
        deduped: List[str] = []
        for b in badges:
            k = unicodedata.normalize("NFC", (b or "").strip()).lower()
            if not k or k in seen_b:
                continue
            seen_b.add(k)
            deduped.append(b.strip())
        out["badges"] = deduped
    return out


def _compute_post_id_from_nodes(nodes: List[Dict[str, Any]]) -> Optional[str]:
    """Compute parent_post_id from the post header nodes at top of comment view.

    Post author node has is_author_hint=True and x≈34 (left-aligned, not indented).
    Post body is the first long text at x≈34 below the author.
    """
    import hashlib
    # Author hint at x < 60 (post author avatar, e.g. "Ảnh đại diện của Khanh Châu")
    post_author = next(
        (n["text"] for n in nodes if n.get("is_author_hint") and n["bounds"][0] < 60),
        None,
    )
    if not post_author:
        return None
    # First substantial body text at x < 60
    post_body = next(
        (n["text"] for n in nodes
         if not n.get("is_author_hint") and n["bounds"][0] < 60 and len(n["text"]) > 20),
        "",
    )
    raw = f"{post_author}\x00{post_body[:120]}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _find_binh_luan_button_in_element(element) -> Optional[Tuple[int, int, int]]:
    """Topmost ``Bình luận`` Button in subtree → (y1, y2, y_mid)."""
    best: Optional[Tuple[int, int, int]] = None
    best_y1 = 10**9
    for node in element.iter():
        if "Button" not in (node.get("class") or ""):
            continue
        t = (node.get("text") or "").strip()
        d = (node.get("content-desc") or "").strip()
        if t != "Bình luận" and d != "Bình luận":
            continue
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
        if not m:
            continue
        y1, y2 = int(m.group(2)), int(m.group(4))
        y_mid = (y1 + y2) // 2
        if y1 < best_y1:
            best_y1 = y1
            best = (y1, y2, y_mid)
    return best


def _legacy_last_binh_luan_anchors(root) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Original behavior: last ``Bình luận`` on screen (comment sheet / fallback)."""
    action_btn_y2: Optional[int] = None
    action_btn_y_mid: Optional[int] = None
    for node in root.iter():
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        cls = node.get("class", "")
        if (text == "Bình luận" or desc == "Bình luận") and "Button" in cls:
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
            if m:
                y1, y2 = int(m.group(2)), int(m.group(4))
                action_btn_y2 = y2
                action_btn_y_mid = (y1 + y2) // 2
    cy_max = _feed_comment_y_max(root, action_btn_y_mid)
    return action_btn_y2, action_btn_y_mid, cy_max


def _resolve_comment_region_anchors(
    root,
    row_match_pid: Optional[str],
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Pick (action_btn_y2, action_btn_y_mid, comment_y_max) for feed comment previews.

    - Comment / thread sheet → last ``Bình luận`` (legacy).
    - Feed RecyclerView: match ``row_match_pid`` to the row's ``_extract_post`` pid, else
      use the **topmost** row that has a ``Bình luận`` button (aligns with
      ``_fb_comment_parent_pid`` = ``posts[0]`` and tap_selector top button).
    """
    if _hierarchy_is_fb_comment_sheet(root):
        return _legacy_last_binh_luan_anchors(root)

    containers = root.xpath(_XPATH_RECYCLER) or root.xpath(_XPATH_LIST)
    if not containers:
        return _legacy_last_binh_luan_anchors(root)

    feed = _pick_feed_container(containers, root)
    children = feed.findall("node")
    if not children:
        return _legacy_last_binh_luan_anchors(root)

    rows: List[Tuple[int, Optional[Dict[str, Any]], Optional[Tuple[int, int, int]], Optional[int]]] = []
    for feed_item_index, candidate in enumerate(children):
        if _is_ad_container(candidate):
            continue
        cb = _parse_bounds(candidate)
        y_top = cb[1] if cb else 10**9
        card_bottom = cb[3] if cb else None
        btn = _find_binh_luan_button_in_element(candidate)
        post: Optional[Dict[str, Any]] = None
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        if nodes:
            fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
            post = _extract_post(
                nodes,
                0,
                structural_type_hint=_structural_post_type_hint(candidate),
                resource_id_media_hint=_resource_id_media_hint(candidate),
                fb_post_id=fb_pid,
                fb_group_id=fb_gid,
                permalink_candidates=perms,
                feed_item_index=feed_item_index,
            )
        rows.append((y_top, post, btn, card_bottom))

    if row_match_pid:
        for _yt, post, btn, cbot in sorted(rows, key=lambda r: r[0]):
            if post and post.get("_pid") == row_match_pid and btn:
                _y1, y2, y_mid = btn
                return y2, y_mid, cbot

    with_btn = [(yt, post, btn, cbot) for yt, post, btn, cbot in rows if btn]
    if with_btn:
        with_btn.sort(key=lambda r: (r[0], r[2][0] if r[2] else 0))
        _yt, _post, btn, cbot = with_btn[0]
        _y1, y2, y_mid = btn
        return y2, y_mid, cbot

    return _legacy_last_binh_luan_anchors(root)


def parse_fb_comments_from_xml(
    xml: str,
    parent_post_id: Optional[str] = None,
    max_items: int = 50,
) -> List[Dict[str, Any]]:
    """Parse comments from current screen XML.

    Works for both:
    - Feed view: extracts comment-preview nodes below post action buttons
    - Post detail view: extracts all visible comments

    Lọc sơ bộ: cùng card RecyclerView với nút Bình luận của **đúng bài**
    (khớp ``parent_post_id`` ↔ ``_pid`` hàng feed, hoặc hàng trên cùng có nút),
    bỏ toolbar phải (x0 lớn), bỏ chuỗi tìm kiếm / menu / bàn phím.

    Each comment dict: author, text, timestamp, likes, reactions (same as likes when set),
    optional post_reactions / post_shares (parent post header), parent_post_id, comment_key, …
    First element may be {_type: post_stats, reactions, shares} when the header exposes counts.

    parent_post_id is:
    1. Passed in externally (from executor ctx), OR
    2. Auto-derived from the post header nodes in the XML (for post detail view)
    """
    root = _parse_xml(xml)
    if root is None:
        return []

    all_nodes = _collect_text_nodes(root, toolbar_cutoff_y=200)
    if not all_nodes:
        return []

    row_match_pid = parent_post_id
    if parent_post_id is None:
        parent_post_id = _compute_post_id_from_nodes(all_nodes)

    action_btn_y2, action_btn_y_mid, comment_y_max = _resolve_comment_region_anchors(
        root, row_match_pid
    )
    screen_w, _screen_h = _infer_screen_size(root)
    # Loại chip cạnh phải (Tìm kiếm trong nhóm, Công cụ khác…) — x0 thường > ~64% màn hình.
    comment_x_max = max(380, int(screen_w * 0.64))

    # Filter: main column x≥150, plus narrow left avatar name strip (thread / OP row).
    # is_author_hint (ảnh đại diện) allowed only on that strip so post header hints
    # in other layouts stay excluded when they do not match strip geometry.
    def _in_comment_vertical_band(n: Dict[str, Any]) -> bool:
        x0 = n["bounds"][0]
        if x0 >= comment_x_max:
            # Reaction count sits on the far right; still part of the comment row.
            if x0 < screen_w - 24 and _is_comment_reaction_count_row(n["text"]):
                pass
            else:
                return False
        if action_btn_y2 is not None and n["cy"] <= action_btn_y2:
            return False
        if comment_y_max is not None and n["bounds"][1] >= comment_y_max:
            return False
        return True

    comment_nodes: List[Dict[str, Any]] = []
    for n in all_nodes:
        if not _in_comment_vertical_band(n):
            continue
        if _is_compact_comment_action_label(n["text"], list(n["bounds"])):
            continue
        if n.get("is_author_hint") and not _is_comment_left_avatar_name_strip(n):
            continue
        if n["bounds"][0] >= 150:
            comment_nodes.append(n)
        elif _is_comment_left_avatar_name_strip(n):
            comment_nodes.append(n)

    if not comment_nodes:
        return []

    # Row alignment + left column before main column (badge vs avatar same band).
    comment_nodes.sort(key=lambda n: (n["bounds"][1] // 35, n["bounds"][0]))

    clusters = _cluster_into_comments(comment_nodes)
    result: List[Dict[str, Any]] = []
    last_kept_body: Optional[Dict[str, Any]] = None
    for cluster in clusters:
        if len(result) >= max_items:
            break
        cluster_min_x = min((n["bounds"][0] for n in cluster if n["bounds"]), default=150)
        comment = _extract_comment(cluster, parent_post_id, cluster_min_x=cluster_min_x)
        if not comment or _is_comment_row_parse_noise(comment):
            continue
        if _is_duplicate_short_author_footer_row(comment, last_kept_body):
            continue
        result.append(comment)
        last_kept_body = comment

    # Prepend post-level stats from the comment view header (reactions, shares)
    # so the executor can update the parent post's stats in the DB.
    header_stats = _extract_header_stats(root)
    if header_stats:
        result.insert(0, header_stats)

    # Denormalize parent post engagement onto each comment row (saved in raw_data / export).
    _pr = header_stats.get("reactions") if header_stats else None
    _ps = header_stats.get("shares") if header_stats else None
    if _pr is not None or _ps is not None:
        for c in result:
            if c.get("_type") == "post_stats":
                continue
            if _pr is not None:
                c["post_reactions"] = _pr
            if _ps is not None:
                c["post_shares"] = _ps

    return result


def _dedup_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate comments: same author + text[:60] = same comment."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for c in comments:
        key = c.get("comment_key") or (c["author"], c["text"][:60])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _post_id_from_ctx(ctx: Dict[str, Any], post_id_var: Optional[str]) -> Optional[str]:
    """Read parent_post_id from ctx. Returns None → parser will auto-derive from XML.

    Scenarios set ``ctx['_fb_comment_parent_pid']`` after ``fb_posts`` (top row ``_pid``)
    and pass ``parent_post_id_var`` on ``fb_comments`` extract — required when the
    comment-sheet header does not yield a stable id (``_compute_post_id_from_nodes``).
    """
    if post_id_var:
        return ctx.get(post_id_var)
    return None


_SEE_MORE_EXPAND_PHRASES: Tuple[str, ...] = (
    "see more",
    "xem thêm",
    "view more comments",
    "view more replies",
    "xem thêm bình luận",
    "xem thêm câu trả lời",
)

# FB often exposes 2+ a11y nodes for the same "Xem thêm" (TextView + Button, bounds off by a few px).
# Tapping both toggles expand → collapse. Dedupe by tap center within this Manhattan radius.
_SEE_MORE_TAP_CENTER_DEDUP_PX: int = 52


def _bounds_center(b: Tuple[int, int, int, int]) -> Tuple[int, int]:
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def _tap_centers_within(b1: Tuple[int, int, int, int], b2: Tuple[int, int, int, int], max_d: int) -> bool:
    x1, y1 = _bounds_center(b1)
    x2, y2 = _bounds_center(b2)
    return abs(x1 - x2) <= max_d and abs(y1 - y2) <= max_d


def _resolve_expand_clickable_bounds(node) -> Optional[Tuple[int, int, int, int]]:
    if (node.get("clickable") or "").lower() == "true":
        b = _parse_bounds(node)
        if b:
            return b
    cur = node
    for _ in range(6):
        cur = cur.getparent()
        if cur is None:
            break
        if (cur.get("clickable") or "").lower() == "true":
            b = _parse_bounds(cur)
            if b:
                return b
    return None


def _expand_clickable_area(b: Tuple[int, int, int, int]) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _bounds_contains_outer_inner(
    outer: Tuple[int, int, int, int], inner: Tuple[int, int, int, int],
) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _collect_see_more_tap_plan(root) -> List[Tuple[int, int, int, int]]:
    """Ordered tap targets: prefer Button, then smallest area; skip wrapper rows."""
    if root is None:
        return []
    nodes = root.xpath('//node[@text or @content-desc]')
    candidates: List[Tuple[int, int, Tuple[int, int, int, int]]] = []
    for node in nodes:
        txt = ((node.get("text") or "") + " " + (node.get("content-desc") or "")).strip().lower()
        if not txt or not any(k in txt for k in _SEE_MORE_EXPAND_PHRASES):
            continue
        b = _resolve_expand_clickable_bounds(node)
        if not b:
            continue
        cls = node.get("class") or ""
        btn_prio = 0 if "Button" in cls else 1
        candidates.append((btn_prio, _expand_clickable_area(b), b))
    candidates.sort(key=lambda x: (x[0], x[1]))
    out: List[Tuple[int, int, int, int]] = []
    for _btn_prio, area, b in candidates:
        if any(
            a2 < area and _bounds_contains_outer_inner(b, b2)
            for _p2, a2, b2 in candidates
        ):
            continue
        if any(_tap_centers_within(b, ob, _SEE_MORE_TAP_CENTER_DEDUP_PX) for ob in out):
            continue
        out.append(b)
    return out


def _xml_has_actionable_see_more_expand(xml: str) -> bool:
    """True if hierarchy has at least one tappable See-more / Xem thêm affordance."""
    if not (xml or "").strip():
        return False
    root = _parse_xml(xml)
    return bool(_collect_see_more_tap_plan(root))


def _expand_see_more(
    device,
    max_passes: int = 5,
    scroll_between: bool = False,
    scroll_distance: float = 0.3,
    max_total_taps: int = 40,
    no_change_threshold: int = 3,
) -> int:
    """Tap visible 'See more' / 'Xem thêm' affordances.

    **One tap per fresh hierarchy dump.** Expanding the first block reflows the tree;
    reusing coordinates from a stale plan taps wrong nodes (next ``Xem thêm`` may move
    or leave the tree). After each tap we ``hierarchy_xml`` again and pick the topmost
    remaining target (min center Y, then X).

    Args:
        max_passes: how many expand+redump cycles to attempt.
        scroll_between: if True, do a small scroll down between passes so that
            content pushed below the viewport is revealed and can also be expanded.
            Useful for very long posts where the full article spans multiple screens.
        scroll_distance: fraction of screen height to scroll between passes (0–1).
    Returns total count expanded."""
    total = 0
    no_change_streak = 0

    for pass_num in range(max_passes):
        if total >= max_total_taps:
            break

        if pass_num > 0 and scroll_between:
            # Progressive hydration: move viewport to trigger next text chunk render.
            device.scroll(direction="down", distance=scroll_distance, duration_ms=780)
            time.sleep(1.0)

        expanded_this_pass = 0
        try:
            # Inner: keep tapping while each new dump still lists a see-more; one tap per dump.
            while total < max_total_taps:
                xml = device.hierarchy_xml(force_refresh=True)
                if not xml:
                    break
                root = _parse_xml(xml)
                if root is None:
                    break
                plan = _collect_see_more_tap_plan(root)
                if not plan:
                    break
                # Top-first: expanding upper blocks is less likely to invalidate coords below
                # in the same frame; stale lower bounds were the main mis-tap source.
                b = min(plan, key=lambda bb: (_bounds_center(bb)[1], _bounds_center(bb)[0]))
                cx, cy = _bounds_center(b)
                device.tap(cx, cy)
                expanded_this_pass += 1
                total += 1
                time.sleep(0.4)
        except Exception:
            break
        if expanded_this_pass:
            # Long posts: layout + network need more than a fixed 1s.
            time.sleep(1.5 + expanded_this_pass * 0.2)
            no_change_streak = 0
        else:
            no_change_streak += 1
            if no_change_streak >= no_change_threshold:
                break

            # One extra viewport nudge can reveal another "Xem thêm" layer.
            if scroll_between:
                device.scroll(direction="down", distance=max(0.15, scroll_distance / 2), duration_ms=720)
                time.sleep(0.85)
    return total


def expand_see_more_with_lazy_hydration(
    device,
    *,
    max_rounds: int = 6,
    scroll_distance: float = 0.25,
    scroll_settle_s: float = 0.8,
    settle_base: float = 1.5,
    settle_per_tap: float = 0.2,
    max_total_taps: int = 40,
) -> int:
    """Tap visible "See more" / "Xem thêm" → wait → re-dump; repeat until XML stable or max_rounds.

    Does **not** scroll the feed between rounds (avoids viewport drift on extract).
    ``scroll_distance`` is kept for API compatibility; only ``_expand_see_more`` internals
    use it when ``scroll_between`` is enabled there (always False here).

    When there are no See-more affordances on screen and nothing was tapped, stop.
    """
    total_taps = 0
    for _ in range(max(1, max_rounds)):
        if total_taps >= max_total_taps:
            break
        xml_before = device.hierarchy_xml(force_refresh=True) or ""
        remaining = max_total_taps - total_taps
        taps = _expand_see_more(
            device,
            max_passes=1,
            scroll_between=False,
            scroll_distance=scroll_distance,
            max_total_taps=remaining,
            no_change_threshold=1,
        )
        total_taps += taps
        if taps == 0 and not _xml_has_actionable_see_more_expand(xml_before):
            break
        if taps:
            time.sleep(settle_base + taps * settle_per_tap)
        time.sleep(scroll_settle_s)
        xml_after = device.hierarchy_xml(force_refresh=True) or ""
        if xml_before == xml_after:
            break
    return total_taps


def prefetch_viewport_scrolls(
    device,
    *,
    passes: int = 3,
    distance: float = 0.3,
    pause_s: float = 0.7,
) -> None:
    """Nudge feed down so lazy text below the fold gets accessibility nodes."""
    for _ in range(max(0, passes)):
        try:
            device.scroll(direction="down", distance=distance)
        except Exception:
            break
        time.sleep(pause_s)


def _extract_header_stats(root) -> Optional[Dict[str, Any]]:
    """Extract post-level stats from the comment view header area (y < 250).

    When a post's comment section is open, Facebook shows a header row with:
    - Reactions count: a Button with text="83" (numeric only)
    - Shares count: a Button with text="42 lượt chia sẻ"

    These nodes sit above toolbar_cutoff_y=200, so they're invisible to the
    normal comment extractor. This function scans for them explicitly.
    """
    reactions: Optional[str] = None
    shares: Optional[str] = None
    for node in root.iter():
        bounds = _parse_bounds(node)
        if not bounds:
            continue
        # Only consider nodes completely above y=260 (header area)
        if bounds[1] > 260:
            continue
        cls = node.get("class", "")
        if "Button" not in cls:
            continue
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        t = text or desc
        if not t:
            continue
        # Numeric-only → reactions count (e.g. "83")
        if re.match(r"^\d[\d.,]*[KMkm]?$", t) and reactions is None:
            reactions = t
            continue
        # "N lượt chia sẻ" → shares count
        m = _RE_SHARES.search(t)
        if m and shares is None:
            shares = m.group(1)
            continue
        # EN / combined labels (e.g. "1,2K lượt thích. Nút Thích.")
        if reactions is None or shares is None:
            st = _parse_stats(t)
            if reactions is None and st.get("reactions"):
                reactions = st["reactions"]
            if shares is None and st.get("shares"):
                shares = st["shares"]

    if reactions is None and shares is None:
        return None
    return {"_type": "post_stats", "reactions": reactions, "shares": shares}
