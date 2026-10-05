"""Content type registry — platform-qualified validation (DF-T-06-001)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.content.errors import GENERIC_CONTENT_TYPES, ContentTypeError

log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300
_GENERIC_SUGGESTIONS = {
    "post": ["threads_post"],
    "comment": ["tiktok_comment", "threads_comment", "ig_comment"],
    "video": ["tiktok_video"],
    "thread": ["threads_post", "threads_comment"],
    "media": ["ig_media"],
}


class RegistryNotInitializedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContentTypeEntry:
    code: str
    platform: str
    object_kind: str
    status: str
    parent_kinds: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "platform": self.platform,
            "object_kind": self.object_kind,
            "status": self.status,
            "parent_kinds": self.parent_kinds,
            "description": self.description,
        }


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None
    suggestions: list[str] = field(default_factory=list)
    entry: ContentTypeEntry | None = None


class ContentTypeRegistry:
    """In-memory registry backed by content_types table."""

    def __init__(self) -> None:
        self._entries: dict[str, ContentTypeEntry] = {}
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_initialized(self) -> bool:
        return bool(self._entries)

    def get(self, code: str) -> ContentTypeEntry | None:
        return self._entries.get(code)

    def list(self, *, active_only: bool = True) -> list[ContentTypeEntry]:
        items = list(self._entries.values())
        if active_only:
            items = [e for e in items if e.status == "active"]
        return sorted(items, key=lambda e: e.code)

    def is_active(self, code: str) -> bool:
        entry = self.get(code)
        return entry is not None and entry.status == "active"

    def validate(self, code: str) -> ValidationResult:
        if not self.is_initialized:
            raise RegistryNotInitializedError("content type registry not loaded")

        normalized = (code or "").strip().lower()
        if not normalized:
            return ValidationResult(ok=False, reason="EMPTY")

        if normalized in GENERIC_CONTENT_TYPES:
            suggestions = _GENERIC_SUGGESTIONS.get(normalized, [])
            if not suggestions:
                suggestions = [e.code for e in self.list() if normalized in e.object_kind][:4]
            return ValidationResult(ok=False, reason="GENERIC", suggestions=suggestions)

        entry = self.get(normalized)
        if entry is None:
            return ValidationResult(ok=False, reason="NOT_REGISTERED")

        if entry.status == "deprecated":
            replacements = [
                e.code
                for e in self.list()
                if e.platform == entry.platform and e.object_kind == entry.object_kind
            ]
            return ValidationResult(
                ok=False,
                reason="DEPRECATED",
                suggestions=replacements,
                entry=entry,
            )

        if entry.status != "active":
            return ValidationResult(ok=False, reason="NOT_ACTIVE", entry=entry)

        return ValidationResult(ok=True, entry=entry)

    async def refresh(self, db: AsyncSession) -> int:
        async with self._lock:
            return await self._load(db)

    async def ensure_fresh(self, db: AsyncSession) -> None:
        if time.monotonic() - self._loaded_at < _CACHE_TTL_SECONDS and self.is_initialized:
            return
        async with self._lock:
            if time.monotonic() - self._loaded_at < _CACHE_TTL_SECONDS and self.is_initialized:
                return
            await self._load(db)

    async def _load(self, db: AsyncSession) -> int:
        from db.models.content import ContentType

        try:
            result = await db.execute(select(ContentType).order_by(ContentType.code))
            rows = result.scalars().all()
        except Exception:
            result = await db.execute(
                text(
                    """
                    SELECT code, platform, object_kind, status, parent_kinds_json, description
                    FROM content_types
                    ORDER BY code
                    """
                )
            )
            rows = result.fetchall()

        entries: dict[str, ContentTypeEntry] = {}
        for row in rows:
            if hasattr(row, "code"):
                parent_raw = row.parent_kinds_json
                if isinstance(parent_raw, str):
                    parent_kinds = json.loads(parent_raw or "[]")
                else:
                    parent_kinds = list(parent_raw or [])
                entry = ContentTypeEntry(
                    code=row.code,
                    platform=row.platform,
                    object_kind=row.object_kind,
                    status=row.status,
                    parent_kinds=parent_kinds,
                    description=row.description or "",
                )
            else:
                parent_kinds = row.parent_kinds_json
                if isinstance(parent_kinds, str):
                    parent_kinds = json.loads(parent_kinds or "[]")
                entry = ContentTypeEntry(
                    code=row[0],
                    platform=row[1],
                    object_kind=row[2],
                    status=row[3],
                    parent_kinds=list(parent_kinds or []),
                    description=row[5] or "",
                )
            entries[entry.code] = entry

        self._entries = entries
        self._loaded_at = time.monotonic()
        log.info("content type registry loaded: %d entries", len(entries))
        return len(entries)


_registry = ContentTypeRegistry()


def get_registry() -> ContentTypeRegistry:
    return _registry


def validate_content_type(code: str) -> tuple[bool, str | None]:
    """Legacy-compatible helper returning (ok, reason)."""
    result = _registry.validate(code)
    return result.ok, result.reason


async def init_registry(db: AsyncSession) -> None:
    count = await _registry.refresh(db)
    if count == 0:
        raise RegistryNotInitializedError("content_types table is empty after migration")


def seed_registry(entries: list[ContentTypeEntry] | None = None) -> None:
    """Load registry in-memory (tests / fallback)."""
    if entries is None:
        entries = [
            ContentTypeEntry("tiktok_video", "tiktok", "video", "active", [], "TikTok video"),
            ContentTypeEntry("tiktok_comment", "tiktok", "comment", "active", ["tiktok_video"], "TikTok comment"),
            ContentTypeEntry("threads_post", "threads", "post", "active", [], "Threads post"),
            ContentTypeEntry("threads_comment", "threads", "comment", "active", ["threads_post"], "Threads comment"),
            ContentTypeEntry("ig_media", "instagram", "media", "active", [], "Instagram media"),
            ContentTypeEntry("ig_comment", "instagram", "comment", "active", ["ig_media"], "Instagram comment"),
            ContentTypeEntry("ig_profile", "instagram", "profile", "active", [], "Instagram profile"),
        ]
    _registry._entries = {entry.code: entry for entry in entries}
    _registry._loaded_at = time.monotonic()


def require_valid_content_type(code: str, *, caller_id: str | None = None) -> ContentTypeEntry:
    """Validate and return registry entry; raises ContentTypeError on failure."""
    result = _registry.validate(code)
    if result.ok and result.entry:
        try:
            from web.metrics import content_type_validate_total

            content_type_validate_total.labels(result="ok").inc()
        except Exception:
            pass
        return result.entry

    reason = result.reason or "INVALID"
    code_map = {
        "GENERIC": "CONTENT_TYPE_GENERIC_REJECTED",
        "NOT_REGISTERED": "CONTENT_TYPE_NOT_REGISTERED",
        "DEPRECATED": "CONTENT_TYPE_DEPRECATED",
        "NOT_ACTIVE": "CONTENT_TYPE_NOT_REGISTERED",
        "EMPTY": "CONTENT_TYPE_NOT_REGISTERED",
    }
    error_code = code_map.get(reason, "CONTENT_TYPE_NOT_REGISTERED")
    try:
        from web.metrics import content_type_validate_total

        content_type_validate_total.labels(result=reason.lower()).inc()
    except Exception:
        pass
    log.warning(
        "invalid content_type=%s reason=%s caller=%s suggestions=%s",
        code,
        reason,
        caller_id,
        result.suggestions,
    )
    raise ContentTypeError(
        f"Invalid content type: {code}",
        code=error_code,
        details={"suggestions": result.suggestions, "reason": reason},
    )
