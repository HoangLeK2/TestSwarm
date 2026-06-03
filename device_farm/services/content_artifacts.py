"""Derive content evidence artifacts from stored content items."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from db.models.content import ContentItem

_INLINE_HIERARCHY_KEYS = (
    "hierarchy",
    "hierarchy_xml",
    "ui_hierarchy",
    "xml",
    "page_source",
)
_INLINE_TEXT_KEYS = (
    "extraction_text",
    "ocr_text",
    "extracted_text",
    "hierarchy_summary",
)
_URL_KEYS = (
    "hierarchy_url",
    "hierarchy_path",
    "screenshot_url",
    "xml_url",
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def content_images_enabled() -> bool:
    return _env_bool("DEVICE_FARM_CONTENT_IMAGES_ENABLED", False)


def normalize_artifact_url(url: str | None) -> str | None:
    if not url:
        return None
    value = str(url).strip()
    if not value:
        return None
    if value.startswith(("http://", "https://", "/")):
        return value
    if "/captures/" in value:
        return value[value.index("/captures/") :]
    if value.startswith("captures/"):
        return f"/{value}"
    if "/screenshots/" in value:
        return value[value.index("/screenshots/") :]
    if value.startswith("screenshots/"):
        return f"/{value}"
    return value


def _kind_for_execution_artifact(art_type: str, url: str) -> str:
    """Map execution step artifact types to preview kinds (proxy URLs lack extensions)."""
    lowered = art_type.lower()
    if "screenshot" in lowered or lowered.endswith(".element") or ".element" in lowered:
        return "image"
    if "hierarchy" in lowered or "selector" in lowered:
        return "xml"
    return _guess_kind(url)


def _guess_kind(value: str, *, mime_hint: str | None = None) -> str:
    if mime_hint:
        if mime_hint.startswith("image/"):
            return "image"
        if mime_hint in ("application/xml", "text/xml"):
            return "xml"
        if mime_hint == "application/json":
            return "json"
        if mime_hint.startswith("text/"):
            return "text"
    stripped = value.lstrip()
    if stripped.startswith("<"):
        return "xml"
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    path = value.split("?", 1)[0].lower()
    if re.search(r"\.(png|jpe?g|webp|gif)$", path):
        return "image"
    if path.endswith(".xml"):
        return "xml"
    if path.endswith(".json"):
        return "json"
    return "text"


def _mime_for_kind(kind: str, path: str | None = None) -> str:
    if path:
        guessed, _ = mimetypes.guess_type(path)
        if guessed:
            return guessed
    return {
        "image": "image/png",
        "xml": "application/xml",
        "json": "application/json",
        "text": "text/plain",
    }.get(kind, "application/octet-stream")


def _artifact_base(
    *,
    artifact_id: str,
    kind: str,
    label: str,
    source: str,
    url: str | None = None,
    inline: bool = False,
    size_bytes: int | None = None,
    status: str = "available",
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "kind": kind,
        "label": label,
        "source": source,
        "url": normalize_artifact_url(url),
        "inline": inline,
        "size_bytes": size_bytes,
        "status": status,
        "mime_type": _mime_for_kind(kind, url),
    }


def _inline_hierarchy_label(key: str) -> str:
    if key == "hierarchy_xml":
        return "XML giao diện"
    return f"XML ({key})"


def _item_has_persisted_screenshot(item: ContentItem) -> bool:
    return bool(str(getattr(item, "screenshot_path", None) or "").strip())


def _item_has_inline_hierarchy(item: ContentItem) -> bool:
    raw = item.raw_data if isinstance(item.raw_data, dict) else {}
    return any(raw.get(k) for k in _INLINE_HIERARCHY_KEYS)


def _base_has_screenshot(artifacts: list[dict[str, Any]]) -> bool:
    return any(a.get("id") == "screenshot" for a in artifacts)


def _base_has_hierarchy(artifacts: list[dict[str, Any]]) -> bool:
    return any(
        str(a.get("id", "")).startswith("inline:")
        and "hierarchy" in str(a.get("source", ""))
        for a in artifacts
    )


def _screenshot_label_for_item(item: ContentItem) -> str:
    ct = str(getattr(item, "content_type", None) or "").lower()
    level = int(getattr(item, "item_level", 0) or 0)
    if ct.endswith("comment") or level > 0:
        return "Màn hình bình luận"
    if ct.endswith("post") or level == 0:
        return "Ảnh bài viết"
    return "Screenshot"


def _pick_primary_hierarchy(raw: dict[str, Any]) -> tuple[str, Any] | None:
    """Single hierarchy blob from crawl (same UI moment as screenshot_path)."""
    for key in _INLINE_HIERARCHY_KEYS:
        value = raw.get(key)
        if value:
            return key, value
    return None


def collect_primary_content_artifacts(item: ContentItem) -> list[dict[str, Any]]:
    """At most one screenshot + one XML for content detail UI."""
    artifacts: list[dict[str, Any]] = []
    raw = item.raw_data if isinstance(item.raw_data, dict) else {}

    if content_images_enabled() and item.screenshot_path:
        path = str(item.screenshot_path)
        artifacts.append(
            _artifact_base(
                artifact_id="screenshot",
                kind=_guess_kind(path),
                label=_screenshot_label_for_item(item),
                source="screenshot_path",
                url=path,
            )
        )

    picked = _pick_primary_hierarchy(raw)
    if picked:
        key, value = picked
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, indent=2)
            kind = "json"
        else:
            text = str(value)
            kind = _guess_kind(text)
        artifacts.append(
            _artifact_base(
                artifact_id="inline:hierarchy_xml",
                kind=kind,
                label=_inline_hierarchy_label(key),
                source=f"raw_data.{key}",
                inline=True,
                size_bytes=len(text.encode("utf-8")),
            )
        )

    return artifacts


def collect_content_artifacts(item: ContentItem) -> list[dict[str, Any]]:
    """Alias for UI/detail — one screenshot + one hierarchy XML only."""
    return collect_primary_content_artifacts(item)


def merge_execution_artifacts(
    item: ContentItem,
    base: list[dict[str, Any]],
    execution_steps: list[tuple[str, str | None]],
) -> list[dict[str, Any]]:
    """Append step screenshots/hierarchy from an execution (deduped by URL)."""
    seen_urls = {a.get("url") for a in base if a.get("url")}
    seen_ids = {a["id"] for a in base}
    out = list(base)

    skip_screenshot = _base_has_screenshot(base)
    skip_hierarchy = _base_has_hierarchy(base)

    for art_type, url in execution_steps:
        resolved = normalize_artifact_url(url)
        if not resolved or resolved in seen_urls:
            continue
        if "hierarchy" not in art_type and "screenshot" not in art_type:
            continue
        lowered = art_type.lower()
        if not content_images_enabled() and "screenshot" in lowered:
            continue
        if skip_screenshot and "screenshot" in lowered:
            continue
        if skip_hierarchy and "hierarchy" in lowered:
            continue
        kind = _kind_for_execution_artifact(art_type, resolved)
        if kind not in ("image", "xml", "json", "text"):
            continue
        artifact_id = f"execution:{art_type}"
        if artifact_id in seen_ids:
            suffix = 1
            while f"{artifact_id}:{suffix}" in seen_ids:
                suffix += 1
            artifact_id = f"{artifact_id}:{suffix}"
        seen_ids.add(artifact_id)
        seen_urls.add(resolved)
        out.append(
            _artifact_base(
                artifact_id=artifact_id,
                kind=kind,
                label=art_type.replace("_", " ").replace(".", " · ").title(),
                source=f"execution.{art_type}",
                url=resolved,
            )
        )
    return out


def _find_artifact(
    item: ContentItem,
    artifact_id: str,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    arts = artifacts if artifacts is not None else collect_content_artifacts(item)
    for art in arts:
        if art["id"] == artifact_id:
            return art
    return None


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(__file__))


def _resolve_local_path(url: str) -> str | None:
    path = url
    if path.startswith("/captures/"):
        return os.path.join(_repo_root(), "captures", path[len("/captures/") :])
    if path.startswith("screenshots/"):
        return os.path.join(_repo_root(), path)
    if path.startswith("/screenshots/"):
        return os.path.join(_repo_root(), path.lstrip("/"))
    if os.path.isabs(path) and os.path.isfile(path):
        return path
    candidate = os.path.join(_repo_root(), path.lstrip("/"))
    if os.path.isfile(candidate):
        return candidate
    return None


def _fetch_url_bytes(url: str) -> bytes:
    import httpx

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
    return resp.content


async def read_artifact_bytes(
    item: ContentItem,
    artifact_id: str,
    artifacts: list[dict[str, Any]] | None = None,
) -> tuple[bytes, str, str]:
    """Return (payload, filename, mime_type). Raises FileNotFoundError when missing."""
    art = _find_artifact(item, artifact_id, artifacts)
    if not art:
        raise FileNotFoundError("artifact not found")

    ts = item.extracted_at or item.created_at or datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d%H%M%S")
    content_id = item.id[:8]

    if art.get("inline"):
        raw = item.raw_data if isinstance(item.raw_data, dict) else {}
        source = str(art["source"])
        if source.startswith("raw_data."):
            key = source[len("raw_data.") :]
            if key.startswith("artifacts["):
                idx = int(key.split("[")[1].split("]")[0])
                nested = raw.get("artifacts") or []
                entry = nested[idx] if idx < len(nested) else {}
                value = entry.get("content") or entry.get("body") or ""
            else:
                value = raw.get(key)
            if isinstance(value, (dict, list)):
                payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
                ext = "json"
            else:
                payload = str(value or "").encode("utf-8")
                ext = "xml" if art["kind"] == "xml" else "txt"
            filename = f"content_{content_id}_{artifact_id.replace(':', '_')}_{stamp}.{ext}"
            return payload, filename, art["mime_type"]

    url = art.get("url")
    if not url:
        raise FileNotFoundError("artifact expired")

    if str(url).startswith(("http://", "https://")):
        data = await asyncio.to_thread(_fetch_url_bytes, str(url))
        parsed = urlparse(str(url))
        base = os.path.basename(parsed.path) or f"artifact_{stamp}"
        return data, f"content_{content_id}_{base}", art["mime_type"]

    local = _resolve_local_path(str(url))
    if not local or not os.path.isfile(local):
        raise FileNotFoundError("artifact expired")
    with open(local, "rb") as fh:
        data = fh.read()
    base = os.path.basename(local)
    return data, f"content_{content_id}_{base}", art["mime_type"]


async def read_artifact_text(
    item: ContentItem,
    artifact_id: str,
    *,
    max_chars: int | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> str:
    data, _, _ = await read_artifact_bytes(item, artifact_id, artifacts)
    text = data.decode("utf-8", errors="replace")
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars]
    return text
