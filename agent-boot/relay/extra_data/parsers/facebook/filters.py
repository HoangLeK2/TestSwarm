from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Dict, Optional

from .constants import (
    _CMT_BADGE_LABELS,
    _CMT_EMPTY_BODY_JUNK_AUTHOR,
    _CMT_NOISE_TEXTS,
    _RE_CMT_REACTIONS,
    _RE_CMT_REACTIONS_EN,
    _RE_CMT_TS_SHARE,
    _RE_COMMENT_REACTIONS_LABEL,
    _RE_IMAGE_TYPE,
    _RE_LEAKED_REL_TIME_AS_LABEL,
    _RE_NUMERIC_SHORT,
    _RE_SHARES_COUNT_LABEL,
    _RE_TS,
)

# Responsibility: junk/noise filters for parsed feed/comment rows.

def _keep_soft_junk() -> bool:
    return os.environ.get("FB_KEEP_SOFT_JUNK", "0") == "1"


def _post_body_has_comment_thread_a11y(text: str) -> bool:
    """True if text is mostly FB a11y strings for *comment* rows."""
    t = (text or "").lower()
    markers = (
        "nút thích bình luận của",
        "trả lời bình luận của",
        "nhấn đúp để trả lời bình luận",
    )
    return sum(1 for m in markers if m in t) >= 2


def _is_hashtag_chip(text: str) -> bool:
    """Single-line hashtag button (e.g. #openclaw) — not the post author."""
    s = (text or "").strip()
    if not s.startswith("#") or " " in s or "\n" in s:
        return False
    return len(s) < 48


def _is_junk_recycler_post(post: Dict[str, Any]) -> bool:
    """Rows from comment sheets / thread chips / composer saved as feed posts — drop."""
    author = (post.get("author") or "").strip()
    text = (post.get("text") or "").strip()
    al = author.lower()
    tl = text.lower()
    combined_lc = f"{al} {tl}"

    if (
        al.startswith("ảnh bìa của nhóm")
        or al.startswith("cover photo of group")
        or "nhóm công khai · " in tl
        or "nhóm riêng tư · " in tl
        or ", công khai · " in al and "thành viên" in al
        or ", công khai · " in tl and "thành viên" in tl
        or "public group · " in tl
        or "private group · " in tl
        or "thành viên đã tham gia nhóm" in tl
        or "members have joined" in tl
    ):
        return True

    _SUGGESTION_AUTHORS = (
        "dành cho bạn", "suggested for you", "made for you",
        "xem tất cả những người bạn có thể biết",
        "những người bạn có thể biết",
        "people you may know",
        "gợi ý cho bạn",
        "nhóm gợi ý", "suggested groups",
    )
    if any(al.startswith(tok) or al == tok for tok in _SUGGESTION_AUTHORS):
        return True
    if any(tok in al for tok in ("những người bạn có thể biết", "people you may know")):
        return True

    if al.startswith("lựa chọn khác về") or al.startswith("more options for"):
        return True

    if (
        al.startswith("device farm agent")
        or "identity and pairing" in tl
        or "device details serial" in tl
        or al == "pair device"
    ):
        return True

    if (
        "bạn viết gì đi" in tl
        or "bạn đang nghĩ gì" in tl
        or "what's on your mind" in tl
        or al.startswith("hiển thị trang cá nhân")
        or al.startswith("đi tới trang cá nhân")
        or al.startswith("go to profile")
    ):
        return True

    if (
        al.startswith("khay tin")
        or "khay tin" in tl
        or al == "tạo tin"
        or "your story" in tl and "stories" in tl
    ):
        return True

    # Footer chrome row from the next partially visible feed item.
    if tl == "ẩn bài viết" or tl == "hide post":
        return True

    _TOOLBAR_TOKENS = (
        "đỏ đậm", "in đậm", "in nghiêng", "gạch chân", "màu nền",
        "bold", "italic", "underline", "background color",
    )
    has_time_anchor = bool(str(post.get("timestamp") or "").strip())
    tb_hits = sum(1 for tok in _TOOLBAR_TOKENS if tok in tl)
    if tb_hits >= 2 and len(text) < 160 and not has_time_anchor:
        return True

    head = tl[:40]
    head_hits = sum(1 for tok in _TOOLBAR_TOKENS if tok in head)
    if head_hits >= 2 and not has_time_anchor:
        return True

    author_tb_hits = sum(1 for tok in _TOOLBAR_TOKENS if tok in al)
    if (
        author_tb_hits >= 2
        and (post.get("reactions") is None and post.get("comments") is None and post.get("shares") is None)
        and not _RE_TS.search(author)
    ):
        return True

    if re.match(r"^\+?\d{1,3}$", author) and len(text) < 64:
        return True
    if al == "video sound toggle":
        return True

    if "nút thích." in tl and ("nhấn đúp" in tl or "double tap" in tl or "double-tap" in tl):
        return True

    if author and (not text or not text.strip()) and "," in author and len(author) > 22:
        return True

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


def _comment_line_is_badge(text: str) -> bool:
    """VN/EN badge chip under commenter name."""
    tl = text.strip().lower()
    if len(tl) < 2 or len(tl) > 72:
        return False
    if tl in _CMT_BADGE_LABELS:
        return True
    if any(b in tl for b in _CMT_BADGE_LABELS if len(b) >= 10):
        return True
    if tl.startswith("top ") and "fan" in tl:
        return True
    if tl.startswith("siêu fan") or tl.startswith("fan cứng"):
        return True
    if tl.startswith("fan cuồng"):
        return True
    return False


def _is_cmt_chrome_search_or_post_menu_text(text: str) -> bool:
    """FB search/menu/other chrome strings; not real comment content."""
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
    """Time/share rows for post — should not be merged into comment clusters."""
    t = text.strip()
    if len(t) > 96:
        return False
    tl = t.lower()
    if "chia sẻ với" in tl:
        return True
    if ("•" in t or "·" in t) and _RE_TS.search(t):
        return True
    return False


def _is_comment_reaction_count_row(text: str) -> bool:
    """Right-aligned chip `N cảm xúc` / `N reactions` (for comment area)."""
    t = (text or "").strip()
    return bool(_RE_CMT_REACTIONS.match(t) or _RE_CMT_REACTIONS_EN.match(t))


def _is_comment_image_placeholder_text(text: str) -> bool:
    tl = (text or "").strip().lower()
    return tl in ("ảnh", "photo", "image", "hình ảnh", "picture")


def _is_compact_comment_action_label(text: str, bounds: list[int]) -> bool:
    t = (text or "").strip().lower()
    if t not in ("thích", "trả lời", "like", "reply"):
        return False
    if len(bounds) < 4:
        return False
    return (int(bounds[2]) - int(bounds[0])) < 220


def _is_comment_left_avatar_name_strip(n: Dict[str, Any]) -> bool:
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


def _is_comment_row_parse_noise(c: Dict[str, Any]) -> bool:
    """Nhiễu UI / parse vỡ rõ ràng — bỏ khỏi output `parse_fb_comments_from_xml`."""
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
    """Rows that should not be stored in DB: enough author + body clean rule."""
    if c.get("_type") == "post_stats":
        return False
    if _is_comment_row_parse_noise(c):
        return True
    if not (c.get("text") or "").strip():
        return True
    return False

__all__ = [
    "_keep_soft_junk",
    "_is_junk_recycler_post",
    "_is_junk_parsed_comment_row",
    "_is_comment_row_parse_noise",
    "_is_cmt_noise",
    "_looks_like_comment_timestamp_row",
    "_comment_line_is_badge",
    "_is_comment_reaction_count_row",
    "_is_comment_image_placeholder_text",
    "_is_compact_comment_action_label",
    "_is_comment_left_avatar_name_strip",
    "_is_duplicate_short_author_footer_row",
]

