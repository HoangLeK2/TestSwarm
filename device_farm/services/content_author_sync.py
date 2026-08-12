"""Sync crawled content authors into temporary Facebook profile targets."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.content import ContentItem
from db.models.external_entity import ExternalEntity, ExternalEntityObservation
from tenancy.context import use_tenant_scope

DEFAULT_AUTHOR_CONTENT_TYPES = ("fb_post", "fb_comment")
AUTHOR_PROFILE_STATUS = "candidate"
AUTHOR_PROFILE_CONFIDENCE = "name_source_only"

_SPACE_RE = re.compile(r"\s+")
_ANONYMOUS_AUTHOR_KEYS = {
    "an danh",
    "nguoi an danh",
    "nguoi tham gia an danh",
    "anonymous",
    "anonymous participant",
    "facebook user",
    "nguoi dung facebook",
    "facebook",
    "tac gia",
    "author",
}


@dataclass(frozen=True, slots=True)
class AuthorSyncResult:
    scanned_count: int
    valid_count: int
    created_count: int
    existing_count: int
    skipped_existing_count: int
    skipped_count: int
    skipped_anonymous_count: int
    skipped_invalid_count: int

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned_count": self.scanned_count,
            "valid_count": self.valid_count,
            "created_count": self.created_count,
            "existing_count": self.existing_count,
            "skipped_existing_count": self.skipped_existing_count,
            "skipped_count": self.skipped_count,
            "skipped_anonymous_count": self.skipped_anonymous_count,
            "skipped_invalid_count": self.skipped_invalid_count,
        }


def _strip_marks(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return (
        "".join(char for char in decomposed if not unicodedata.combining(char))
        .replace("đ", "d")
        .replace("Đ", "D")
    )


def normalize_author_name(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return _SPACE_RE.sub(" ", normalized.replace("\u00a0", " ")).strip()


def author_lookup_key(value: str | None) -> str:
    return _SPACE_RE.sub(" ", _strip_marks(normalize_author_name(value)).casefold()).strip()


def is_syncable_author(value: str | None) -> tuple[bool, str]:
    name = normalize_author_name(value)
    if not name:
        return False, "invalid"
    key = author_lookup_key(name)
    if len(name) < 2 or len(name) > 80:
        return False, "invalid"
    if key in _ANONYMOUS_AUTHOR_KEYS:
        return False, "anonymous"
    if any(token in key for token in ("anonymous", "an danh")):
        return False, "anonymous"
    if key.startswith(("xem ", "see ")) and len(key) <= 24:
        return False, "invalid"
    return True, "ok"


def author_source_identity_key(author: str, content_hash: str) -> str:
    raw = f"{author_lookup_key(author)}\x00{str(content_hash or '').strip()}"
    return "author_source:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def sync_author_profiles_from_content(
    db: AsyncSession,
    *,
    org_id: str,
    collection: str | None = None,
    campaign_id: str | None = None,
    execution_id: str | None = None,
    content_types: Sequence[str] | None = None,
    dry_run: bool = False,
    limit: int = 2_000,
    created_by: str | None = None,
) -> AuthorSyncResult:
    """Create name+content scoped Facebook profile candidates from content authors."""
    if not any((collection, campaign_id, execution_id)):
        raise ValueError("collection, campaign_id, or execution_id is required")
    if limit < 1 or limit > 5_000:
        raise ValueError("limit must be between 1 and 5000")

    types = tuple(str(item).strip() for item in (content_types or DEFAULT_AUTHOR_CONTENT_TYPES) if str(item).strip())
    if not types:
        raise ValueError("at least one content_type is required")

    filters: list[Any] = [
        ContentItem.org_id == org_id,
        ContentItem.deleted_at.is_(None),
        ContentItem.author.is_not(None),
        ContentItem.content_hash.is_not(None),
        ContentItem.content_type.in_(types),
    ]
    if collection:
        filters.append(ContentItem.collection == collection)
    if campaign_id:
        filters.append(ContentItem.campaign_id == campaign_id)
    if execution_id:
        filters.append(ContentItem.execution_id == execution_id)

    stmt = (
        select(ContentItem)
        .where(*filters)
        .order_by(ContentItem.extracted_at.desc(), ContentItem.id.desc())
        .limit(limit)
    )
    with use_tenant_scope(org_id):
        rows = list((await db.scalars(stmt)).all())

    scanned = len(rows)
    skipped_anonymous = 0
    skipped_invalid = 0
    candidates: dict[str, tuple[ContentItem, str]] = {}
    for item in rows:
        author = normalize_author_name(item.author)
        ok, reason = is_syncable_author(author)
        if not ok:
            if reason == "anonymous":
                skipped_anonymous += 1
            else:
                skipped_invalid += 1
            continue
        identity_key = author_source_identity_key(author, item.content_hash)
        candidates.setdefault(identity_key, (item, author))

    if not candidates:
        return AuthorSyncResult(
            scanned_count=scanned,
            valid_count=0,
            created_count=0,
            existing_count=0,
            skipped_existing_count=0,
            skipped_count=skipped_anonymous + skipped_invalid,
            skipped_anonymous_count=skipped_anonymous,
            skipped_invalid_count=skipped_invalid,
        )

    identity_keys = list(candidates.keys())
    with use_tenant_scope(org_id):
        existing_ids = set(
            (
                await db.scalars(
                    select(ExternalEntity.identity_key).where(
                        ExternalEntity.org_id == org_id,
                        ExternalEntity.platform == "facebook",
                        ExternalEntity.entity_type == "profile",
                        ExternalEntity.identity_key.in_(identity_keys),
                    )
                )
            ).all()
        )
    existing_count = len(existing_ids)
    create_keys = [key for key in identity_keys if key not in existing_ids]
    skipped_count = skipped_anonymous + skipped_invalid + existing_count
    if dry_run:
        return AuthorSyncResult(
            scanned_count=scanned,
            valid_count=len(create_keys),
            created_count=len(create_keys),
            existing_count=existing_count,
            skipped_existing_count=existing_count,
            skipped_count=skipped_count,
            skipped_anonymous_count=skipped_anonymous,
            skipped_invalid_count=skipped_invalid,
        )

    now = datetime.now(timezone.utc)
    created = 0
    with use_tenant_scope(org_id):
        for key in create_keys:
            item, author = candidates[key]
            attrs = {
                "source": "content_author_sync",
                "author_name": author,
                "source_content_id": item.id,
                "source_content_hash": item.content_hash,
                "source_content_type": item.content_type,
                "source_parent_id": item.parent_id,
                "source_execution_id": item.execution_id,
                "source_campaign_id": item.campaign_id,
                "source_collection": item.collection,
                "source_item_level": item.item_level,
            }
            metrics = {
                "seen_count": 1,
                "post_seen_count": 1 if item.content_type == "fb_post" else 0,
                "comment_seen_count": 1 if item.content_type == "fb_comment" else 0,
            }
            entity = ExternalEntity(
                org_id=org_id,
                platform="facebook",
                entity_type="profile",
                identity_key=key,
                identity_confidence=AUTHOR_PROFILE_CONFIDENCE,
                display_name=author,
                status=AUTHOR_PROFILE_STATUS,
                current_attributes=attrs,
                current_metrics=metrics,
                first_seen_at=item.extracted_at or now,
                last_seen_at=item.extracted_at or now,
                created_by=created_by,
            )
            db.add(entity)
            await db.flush()
            db.add(
                ExternalEntityObservation(
                    org_id=org_id,
                    external_entity_id=entity.id,
                    observed_at=item.extracted_at or now,
                    display_name=author,
                    attributes=attrs,
                    metrics=metrics,
                    raw_data={
                        "content_item_id": item.id,
                        "content_hash": item.content_hash,
                        "author": author,
                    },
                    execution_id=item.execution_id,
                    account_id=item.account_id,
                )
            )
            created += 1
    await db.flush()

    return AuthorSyncResult(
        scanned_count=scanned,
        valid_count=len(create_keys),
        created_count=created,
        existing_count=existing_count,
        skipped_existing_count=existing_count,
        skipped_count=skipped_count,
        skipped_anonymous_count=skipped_anonymous,
        skipped_invalid_count=skipped_invalid,
    )
