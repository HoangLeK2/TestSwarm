from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account_import_format import AccountImportFormat

ALLOWED_DIRECT_FIELDS = {
    "platform",
    "username",
    "password",
    "password_plain",
    "display_name",
    "tags",
    "notes",
    "email",
    "totp_secret",
    "cookies",
    "token",
}
IGNORED_FIELDS = {"", "-", "_", "ignore", "ignored", "skip", "none", "null"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,98}[a-z0-9]$")


class AccountImportFormatError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedTxtAccounts:
    rows: list[dict[str, Any]]
    total: int
    invalid: int


def validate_account_import_fields(fields: Iterable[str]) -> list[str]:
    normalized = [str(field or "").strip() for field in fields]
    if not normalized:
        raise AccountImportFormatError(
            "IMPORT_FORMAT_FIELDS_REQUIRED",
            "fields cannot be empty",
        )
    if "username" not in normalized:
        raise AccountImportFormatError(
            "IMPORT_FORMAT_USERNAME_REQUIRED",
            "fields must include username",
        )
    for field in normalized:
        lowered = field.lower()
        if lowered in IGNORED_FIELDS:
            continue
        if lowered in ALLOWED_DIRECT_FIELDS:
            continue
        if lowered.startswith("metadata.") and len(lowered) > len("metadata."):
            continue
        raise AccountImportFormatError(
            "IMPORT_FORMAT_FIELD_UNSUPPORTED",
            f"Unsupported import field: {field}",
        )
    return normalized


def validate_account_import_slug(slug: str) -> str:
    normalized = slug.strip().lower()
    if not SLUG_RE.match(normalized):
        raise AccountImportFormatError(
            "IMPORT_FORMAT_SLUG_INVALID",
            "slug must be 3-100 chars using lowercase letters, numbers, hyphen or underscore",
        )
    return normalized


def parse_txt_accounts(content: str, fmt: AccountImportFormat) -> ParsedTxtAccounts:
    fields = validate_account_import_fields(fmt.fields or [])
    delimiter = fmt.delimiter or "|"
    rows: list[dict[str, Any]] = []
    total = 0
    invalid = 0
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        total += 1
        parts = [part.strip() for part in line.split(delimiter)]
        row: dict[str, Any] = {"platform": fmt.platform}
        metadata: dict[str, Any] = {}
        for index, field in enumerate(fields):
            key = field.lower()
            if key in IGNORED_FIELDS:
                continue
            value = parts[index].strip() if index < len(parts) else ""
            if not value:
                continue
            if key.startswith("metadata."):
                metadata[key.split(".", 1)[1]] = value
            else:
                row[key] = value
        if metadata:
            row["account_metadata"] = metadata
        if not row.get("platform") or not row.get("username"):
            invalid += 1
            continue
        rows.append(row)
    return ParsedTxtAccounts(rows=rows, total=total, invalid=invalid)


async def list_account_import_formats(
    db: AsyncSession,
    *,
    include_inactive: bool = False,
) -> list[AccountImportFormat]:
    stmt = select(AccountImportFormat).order_by(
        AccountImportFormat.is_builtin.desc(),
        AccountImportFormat.name.asc(),
    )
    if not include_inactive:
        stmt = stmt.where(AccountImportFormat.is_active.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_account_import_format(
    db: AsyncSession,
    *,
    format_id: str | None = None,
    slug: str | None = None,
    active_only: bool = True,
) -> AccountImportFormat | None:
    stmt = select(AccountImportFormat)
    if format_id:
        stmt = stmt.where(AccountImportFormat.id == format_id)
    elif slug:
        stmt = stmt.where(AccountImportFormat.slug == slug)
    else:
        return None
    if active_only:
        stmt = stmt.where(AccountImportFormat.is_active.is_(True))
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()


async def create_account_import_format(
    db: AsyncSession,
    *,
    slug: str,
    name: str,
    fields: list[str],
    delimiter: str = "|",
    platform: str = "facebook",
    description: str = "",
    created_by_user_id: str | None = None,
    is_active: bool = True,
) -> AccountImportFormat:
    row = AccountImportFormat(
        slug=validate_account_import_slug(slug),
        name=name.strip(),
        description=description.strip(),
        delimiter=delimiter or "|",
        platform=platform.strip().lower() or "facebook",
        fields=validate_account_import_fields(fields),
        is_active=is_active,
        is_builtin=False,
        created_by_user_id=created_by_user_id,
    )
    if not row.name:
        raise AccountImportFormatError(
            "IMPORT_FORMAT_NAME_REQUIRED",
            "name cannot be empty",
        )
    db.add(row)
    await db.flush()
    return row


async def update_account_import_format(
    db: AsyncSession,
    row: AccountImportFormat,
    *,
    name: str | None = None,
    description: str | None = None,
    delimiter: str | None = None,
    platform: str | None = None,
    fields: list[str] | None = None,
    is_active: bool | None = None,
) -> AccountImportFormat:
    if name is not None:
        row.name = name.strip()
        if not row.name:
            raise AccountImportFormatError(
                "IMPORT_FORMAT_NAME_REQUIRED",
                "name cannot be empty",
            )
    if description is not None:
        row.description = description.strip()
    if delimiter is not None:
        row.delimiter = delimiter or "|"
    if platform is not None:
        row.platform = platform.strip().lower() or "facebook"
    if fields is not None:
        row.fields = validate_account_import_fields(fields)
    if is_active is not None:
        row.is_active = bool(is_active)
    await db.flush()
    return row


async def count_account_import_formats_by_slug(db: AsyncSession, slug: str) -> int:
    stmt = select(func.count()).select_from(AccountImportFormat).where(
        AccountImportFormat.slug == slug
    )
    return int((await db.execute(stmt)).scalar_one() or 0)
