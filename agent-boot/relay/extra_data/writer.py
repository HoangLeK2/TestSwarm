"""Row shaping for agent-side extra-data ingestion.

Everything here is pure: no database handle, no credentials, no network. The
agent builds rows and hands them to device_farm in the relay reply, and
device_farm is the only process that touches Postgres — see
`device_farm/services/content/edge_ingest.py`.

`content_hash` is computed from the raw item, before any scrubbing or
normalisation, and `parent_id` is that same hash scoped to the run. Changing
when or from what the hash is computed silently breaks deduplication and
detaches every comment from its post. device_farm recomputes the hash and
rejects any it cannot derive from the raw item, so the two sides must agree
exactly.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import ftfy as _ftfy  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _ftfy = None

try:
    import dateparser as _dateparser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _dateparser = None


_RE_RELATIVE_TIME = re.compile(
    r"^\s*(\d+)\s*(giây|phút|giờ|ngày|tuần|tháng|năm|second|minute|hour|day|week|month|year)s?\s*(trước|ago)?\s*$",
    re.IGNORECASE,
)
_RE_CALENDAR_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def clean_text(text: Any) -> Any:
    if not isinstance(text, str) or not text:
        return text
    if _ftfy is None:
        return text.strip()
    try:
        return _ftfy.fix_text(text).strip()
    except Exception:
        return text.strip()


def compute_content_hash(data: dict[str, Any], dedupe_field: str | None = None) -> str:
    if dedupe_field and dedupe_field in data:
        raw = str(data[dedupe_field])
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    normalized = unicodedata.normalize("NFC", raw.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def scope_content_hash(base_hash: str | None, scope: str | None = None) -> str | None:
    if not base_hash:
        return None
    if not scope:
        return base_hash
    return hashlib.sha256(f"{scope}:{base_hash}".encode("utf-8")).hexdigest()


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val).strip()
    if not s:
        return None
    multiplier = 1
    if s[-1].upper() == "K":
        multiplier = 1000
        s = s[:-1].strip()
    elif s[-1].upper() == "M":
        multiplier = 1_000_000
        s = s[:-1].strip()
    elif s[-1].upper() == "B":
        multiplier = 1_000_000_000
        s = s[:-1].strip()
    if multiplier > 1 and "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return int(float(s) * multiplier)
    except (ValueError, TypeError):
        return None


def _normalize_media_urls(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None and str(v).strip()]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed if v is not None and str(v).strip()]
            except Exception:
                pass
        return [s]
    return []


def _parse_captured_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # APK may send milliseconds.
        v = float(value)
        if v > 10_000_000_000:
            v = v / 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    s = str(value or "").strip()
    if s:
        try:
            return datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", s))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _parse_content_date(value: Any, *, captured_at: Any = None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    s = str(value).strip()
    if not s:
        return None
    s_clean = s.replace("\u00a0", " ").replace("\u202f", " ").strip()
    s_lower = s_clean.lower()

    try:
        if "t" in s_lower or "-" in s_lower:
            parsed = datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", s_clean))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    m = _RE_CALENDAR_DATE.match(s_clean)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    base = _parse_captured_at(captured_at)
    if s_lower in {"hôm qua", "yesterday"}:
        return base - timedelta(days=1)
    if s_lower in {"just now", "vừa xong", "bây giờ", "now"}:
        return base

    m = _RE_RELATIVE_TIME.match(s_lower)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit in {"giây", "second"}:
            return base - timedelta(seconds=amount)
        if unit in {"phút", "minute"}:
            return base - timedelta(minutes=amount)
        if unit in {"giờ", "hour"}:
            return base - timedelta(hours=amount)
        if unit in {"ngày", "day"}:
            return base - timedelta(days=amount)
        if unit in {"tuần", "week"}:
            return base - timedelta(weeks=amount)
        if unit in {"tháng", "month"}:
            return base - timedelta(days=30 * amount)
        if unit in {"năm", "year"}:
            return base - timedelta(days=365 * amount)

    if _dateparser is not None:
        try:
            dt = _dateparser.parse(
                s_clean,
                languages=["vi", "en"],
                settings={
                    "RETURN_AS_TIMEZONE_AWARE": True,
                    "PREFER_DAY_OF_MONTH": "first",
                    "TO_TIMEZONE": "UTC",
                    "RELATIVE_BASE": base.replace(tzinfo=None),
                },
            )
            if dt is not None:
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def build_content_item_row(
    data: dict[str, Any],
    context: dict[str, Any],
    *,
    parent_id: str | None = None,
    item_level: int | None = None,
    captured_at: Any = None,
) -> dict[str, Any]:
    scope = context.get("hash_scope") or context.get("execution_id")
    base_hash = compute_content_hash(data, context.get("dedupe_field"))
    content_hash = scope_content_hash(base_hash, scope)
    if parent_id and context.get("parent_id_already_scoped"):
        scoped_parent_id = str(parent_id)
    else:
        scoped_parent_id = scope_content_hash(parent_id, scope) if parent_id else None
    body = clean_text(
        data.get("content")
        or data.get("body")
        or data.get("text")
        or data.get("message")
        or data.get("caption")
        or data.get("description")
        or data.get("image_desc")
    )
    author = clean_text(
        data.get("author")
        or data.get("name")
        or data.get("username")
        or data.get("full_name")
    )
    url = data.get("url") or data.get("permalink") or data.get("link")
    screenshot_path = data.get("_screenshot_path") or data.get("screenshot_path") or None
    if screenshot_path is not None:
        screenshot_path = str(screenshot_path)[:1000] or None
    return {
        "id": str(uuid.uuid4()),
        "collection": context.get("collection") or "default",
        "platform": data.get("platform") or context.get("platform") or None,
        "content_type": data.get("content_type") or context.get("content_type") or "post",
        "title": str(data.get("title") or "")[:500] or None,
        "body": body,
        "author": str(author or "")[:255] or None,
        "author_id": str(data.get("author_id") or "")[:255] or None,
        "url": str(url or "")[:1000] or None,
        "likes_count": _safe_int(_first_present(data, "likes_count", "likes", "reactions", "like")),
        "comments_count": _safe_int(_first_present(data, "comments_count", "comments", "comment")),
        "shares_count": _safe_int(_first_present(data, "shares_count", "shares", "share")),
        "views_count": _safe_int(_first_present(data, "views_count", "views", "view")),
        "media_urls": _normalize_media_urls(_first_present(data, "media_urls", "media_artifacts", "permalink_candidates")),
        "screenshot_path": screenshot_path,
        "raw_data": data,
        "tags": context.get("tags") or "",
        "content_hash": content_hash,
        "parent_id": scoped_parent_id,
        "item_level": int(item_level if item_level is not None else (context.get("item_level") or 0)),
        "device_serial": context.get("device_serial"),
        "campaign_id": context.get("campaign_id") or None,
        "execution_id": context.get("execution_id") or None,
        "scenario_name": context.get("scenario_name") or None,
        "user_id": context.get("user_id") or None,
        "org_id": context.get("org_id") or None,
        "extracted_at": _parse_captured_at(captured_at),
        "content_date": _parse_content_date(
            _first_present(data, "content_date", "posted_at", "published_at", "timestamp", "date", "date_posted"),
            captured_at=captured_at,
        ),
        "created_at": datetime.now(timezone.utc),
    }
