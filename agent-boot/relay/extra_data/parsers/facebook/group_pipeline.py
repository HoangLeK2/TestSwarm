"""Parse Facebook group search result cards from an accessibility hierarchy."""
from __future__ import annotations

import re
import hashlib
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any

_GROUP_SIGNAL_RE = re.compile(
    r"\b((?:nhóm\s+)?(?:công khai|riêng tư)|public\s+group|private\s+group)\b",
    re.IGNORECASE,
)
_EXPLICIT_GROUP_SIGNAL_RE = re.compile(
    r"\b(?:nhóm\s+(?:công khai|riêng tư)|public\s+group|private\s+group)\b",
    re.IGNORECASE,
)
_MEMBER_RE = re.compile(
    r"(?P<count>\d[\d.,\s]*(?:[KMB])?)\s*(?:thành viên|members?)\b",
    re.IGNORECASE,
)


def _member_count(raw: str) -> int | None:
    match = _MEMBER_RE.search(raw)
    if not match:
        return None
    token = match.group("count").replace(" ", "").strip()
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
    signal = _GROUP_SIGNAL_RE.search(label)
    prefix = label[: signal.start()] if signal else label
    return prefix.rstrip(" ,·-").strip()


def parse_group_search_results(
    xml: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], {"reason_code": "invalid_xml", "groups_returned": 0}

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in root.iter():
        if str(node.get("clickable") or "").lower() != "true":
            continue
        label = _card_label(node)
        if not label or not _GROUP_SIGNAL_RE.search(label):
            continue
        if not _EXPLICIT_GROUP_SIGNAL_RE.search(label) and not _MEMBER_RE.search(label):
            continue
        name = _display_name(label)
        identity_name = _identity_name(name)
        if not identity_name or identity_name in seen:
            continue
        seen.add(identity_name)
        lowered = label.casefold()
        privacy = (
            "private"
            if "riêng tư" in lowered or "private group" in lowered
            else "public"
            if "công khai" in lowered or "public group" in lowered
            else None
        )
        metrics: dict[str, Any] = {}
        count = _member_count(label)
        if count is not None:
            metrics["member_count"] = count
        attributes: dict[str, Any] = {
            "locator": {
                "kind": "facebook_group_search_result",
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
            }
        }
        if privacy:
            attributes["privacy"] = privacy
        items.append(
            {
                "platform": "facebook",
                "entity_type": "group",
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
        "reason_code": "ok" if items else "no_groups",
        "groups_returned": len(items),
    }
