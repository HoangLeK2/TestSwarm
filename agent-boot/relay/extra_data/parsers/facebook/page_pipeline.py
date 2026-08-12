"""Parse Facebook page search result cards from an accessibility hierarchy."""
from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any

_PAGE_SIGNAL_RE = re.compile(
    r"(?:^|[,·]\s*)(?:trang|page)\b|"
    r"\b(?:người\s+thích|lượt\s+thích|người\s+theo\s+dõi|followers?|likes?)\b",
    re.IGNORECASE,
)
_EXPLICIT_PAGE_SIGNAL_RE = re.compile(
    r"(?:^|[,·]\s*)(?:trang|page)\b",
    re.IGNORECASE,
)
_LIKE_RE = re.compile(
    r"(?P<count>\d[\d.,\s]*(?:[KMB])?)\s*(?:người\s+thích|lượt\s+thích|likes?)\b",
    re.IGNORECASE,
)
_FOLLOWER_RE = re.compile(
    r"(?P<count>\d[\d.,\s]*(?:[KMB])?)\s*(?:người\s+theo\s+dõi|followers?)\b",
    re.IGNORECASE,
)
_TAB_NAMES = {
    "all",
    "tất cả",
    "tat ca",
    "posts",
    "bài viết",
    "bai viet",
    "people",
    "mọi người",
    "moi nguoi",
    "groups",
    "nhóm",
    "nhom",
    "events",
    "sự kiện",
    "su kien",
    "pages",
    "trang",
}


def _compact_count(raw: str) -> int | None:
    token = raw.replace(" ", "").strip()
    if not token:
        return None
    multiplier = 1
    if token[-1:].upper() in {"K", "M", "B"}:
        multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
            token[-1].upper()
        ]
        token = token[:-1]
        if "," in token and "." not in token:
            token = token.replace(",", ".")
    else:
        token = token.replace(".", "").replace(",", "")
    try:
        return int(float(token) * multiplier)
    except ValueError:
        return None


def _metric_count(pattern: re.Pattern[str], label: str) -> int | None:
    match = pattern.search(label)
    if not match:
        return None
    return _compact_count(match.group("count"))


def _identity_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


def _card_label(node: ET.Element) -> str:
    direct = (node.get("content-desc") or "").strip()
    if direct:
        return direct
    parts = [
        text
        for child in node.iter()
        if (text := (child.get("text") or child.get("content-desc") or "").strip())
    ]
    return ", ".join(dict.fromkeys(parts))


def _display_name(label: str) -> str:
    signal = _PAGE_SIGNAL_RE.search(label)
    prefix = label[: signal.start()] if signal else label
    return prefix.rstrip(" ,·-").strip()


def parse_page_search_results(
    xml: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], {"reason_code": "invalid_xml", "pages_returned": 0}

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in root.iter():
        if str(node.get("clickable") or "").lower() != "true":
            continue
        label = _card_label(node)
        if not label or not _PAGE_SIGNAL_RE.search(label):
            continue
        if not _EXPLICIT_PAGE_SIGNAL_RE.search(label) and not (
            _LIKE_RE.search(label) or _FOLLOWER_RE.search(label)
        ):
            continue
        name = _display_name(label)
        identity_name = _identity_name(name)
        if not identity_name or identity_name in _TAB_NAMES or identity_name in seen:
            continue
        seen.add(identity_name)
        metrics: dict[str, Any] = {}
        like_count = _metric_count(_LIKE_RE, label)
        follower_count = _metric_count(_FOLLOWER_RE, label)
        if like_count is not None:
            metrics["like_count"] = like_count
        if follower_count is not None:
            metrics["follower_count"] = follower_count
        attributes: dict[str, Any] = {
            "locator": {
                "kind": "facebook_page_search_result",
                "version": 1,
                "search_query": name,
                "selector": {
                    "by": "descriptionStartsWith",
                    "value": f"{name},",
                },
                "fallback_selector": {
                    "by": "descriptionContains",
                    "value": name,
                },
            },
        }
        items.append(
            {
                "platform": "facebook",
                "entity_type": "page",
                "display_name": name,
                "identity_key": (
                    "name:"
                    + hashlib.sha256(identity_name.encode("utf-8")).hexdigest()
                ),
                "identity_confidence": "name_only",
                "attributes": attributes,
                "metrics": metrics,
                "raw_data": {
                    "label": label,
                    "bounds": node.get("bounds"),
                },
                "rank": len(items) + 1,
            }
        )
    return items, {
        "reason_code": "ok" if items else "no_pages",
        "pages_returned": len(items),
    }
