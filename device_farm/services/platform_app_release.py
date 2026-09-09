from __future__ import annotations

import hashlib
import asyncio
import os
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, BinaryIO, Iterator

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.platform_app_release import PlatformAppRelease
from services import minio_store

FACEBOOK_PLATFORM = "facebook"
FACEBOOK_PACKAGE = "com.facebook.katana"
APK_CONTENT_TYPE = "application/vnd.android.package-archive"
RELEASE_STATUSES = {"draft", "active", "archived"}
DEFAULT_MAX_APK_BYTES = 250 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024


class PlatformAppReleaseError(Exception):
    code = "PLATFORM_APP_RELEASE_ERROR"
    status_code = 422


class PlatformAppStorageUnavailable(PlatformAppReleaseError):
    code = "OBJECT_STORAGE_UNAVAILABLE"
    status_code = 503


class PlatformAppUploadFailed(PlatformAppReleaseError):
    code = "PLATFORM_APP_UPLOAD_FAILED"
    status_code = 502


@dataclass(frozen=True)
class ApkMetadata:
    package_name: str
    version_name: str
    version_code: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _max_apk_bytes() -> int:
    raw = os.environ.get("DEVICE_FARM_PLATFORM_APP_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_APK_BYTES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_APK_BYTES


def _read_length8(data: bytes, offset: int) -> tuple[int, int]:
    first = data[offset]
    offset += 1
    if first & 0x80:
        second = data[offset]
        offset += 1
        return ((first & 0x7F) << 8) | second, offset
    return first, offset


def _read_length16(data: bytes, offset: int) -> tuple[int, int]:
    first = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    if first & 0x8000:
        second = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        return ((first & 0x7FFF) << 16) | second, offset
    return first, offset


def _decode_string_pool(data: bytes, chunk_offset: int, chunk_size: int) -> list[str]:
    string_count, style_count, flags, strings_start, _styles_start = struct.unpack_from(
        "<IIIII", data, chunk_offset + 8
    )
    offsets_start = chunk_offset + 28
    strings_base = chunk_offset + strings_start
    utf8 = bool(flags & 0x00000100)
    strings: list[str] = []
    for index in range(string_count):
        rel = struct.unpack_from("<I", data, offsets_start + index * 4)[0]
        pos = strings_base + rel
        try:
            if utf8:
                _chars, pos = _read_length8(data, pos)
                byte_len, pos = _read_length8(data, pos)
                raw = data[pos : pos + byte_len]
                strings.append(raw.decode("utf-8", errors="replace"))
            else:
                char_len, pos = _read_length16(data, pos)
                raw = data[pos : pos + char_len * 2]
                strings.append(raw.decode("utf-16le", errors="replace"))
        except Exception:
            strings.append("")
    del style_count, chunk_size
    return strings


def _string_at(strings: list[str], index: int) -> str | None:
    if index < 0 or index >= len(strings):
        return None
    value = strings[index]
    return value if value else None


def _typed_value(strings: list[str], raw_value: int, value_type: int, value_data: int) -> str | None:
    if raw_value != 0xFFFFFFFF:
        return _string_at(strings, raw_value)
    if value_type == 0x03:
        return _string_at(strings, value_data)
    if value_type in {0x10, 0x11}:
        return str(value_data)
    return None


def parse_apk_metadata_from_file(file_obj: BinaryIO) -> ApkMetadata:
    try:
        file_obj.seek(0)
        with zipfile.ZipFile(file_obj) as apk:
            manifest = apk.read("AndroidManifest.xml")
    except KeyError as exc:
        raise PlatformAppReleaseError("APK missing AndroidManifest.xml") from exc
    except zipfile.BadZipFile as exc:
        raise PlatformAppReleaseError("Invalid APK zip") from exc
    finally:
        try:
            file_obj.seek(0)
        except Exception:
            pass

    if len(manifest) < 36:
        raise PlatformAppReleaseError("Invalid AndroidManifest.xml")

    strings: list[str] = []
    offset = 8
    while offset + 8 <= len(manifest):
        chunk_type, _header_size, chunk_size = struct.unpack_from("<HHI", manifest, offset)
        if chunk_size <= 0 or offset + chunk_size > len(manifest):
            break
        if chunk_type == 0x0001:
            strings = _decode_string_pool(manifest, offset, chunk_size)
        elif chunk_type == 0x0102:
            if not strings:
                raise PlatformAppReleaseError("APK manifest string pool missing")
            (
                _line_number,
                _comment,
                _namespace,
                tag_name_idx,
                _attr_start,
                _attr_size,
                attr_count,
                _id_index,
                _class_index,
                _style_index,
            ) = struct.unpack_from("<IIIIHHHHHH", manifest, offset + 8)
            tag_name = _string_at(strings, tag_name_idx)
            if tag_name == "manifest":
                attrs_offset = offset + 36
                attrs: dict[str, str] = {}
                for attr_index in range(attr_count):
                    attr_offset = attrs_offset + attr_index * 20
                    _attr_ns, name_idx, raw_value, _size, _res0, value_type, value_data = struct.unpack_from(
                        "<IIIHBBI", manifest, attr_offset
                    )
                    name = _string_at(strings, name_idx)
                    value = _typed_value(strings, raw_value, value_type, value_data)
                    if name and value is not None:
                        attrs[name] = value
                package_name = (attrs.get("package") or "").strip()
                version_name = (attrs.get("versionName") or "").strip()
                version_code = (attrs.get("versionCode") or "").strip() or None
                if not package_name:
                    raise PlatformAppReleaseError("APK manifest package missing")
                if not version_name:
                    raise PlatformAppReleaseError("APK manifest versionName missing")
                return ApkMetadata(
                    package_name=package_name,
                    version_name=version_name,
                    version_code=version_code,
                )
        offset += chunk_size

    raise PlatformAppReleaseError("APK manifest tag missing")


def parse_apk_metadata(content: bytes) -> ApkMetadata:
    return parse_apk_metadata_from_file(BytesIO(content))


def _file_size(file_obj: BinaryIO) -> int:
    current = file_obj.tell()
    try:
        file_obj.seek(0, os.SEEK_END)
        return file_obj.tell()
    finally:
        file_obj.seek(current)


def _sha256_file(file_obj: BinaryIO, *, max_bytes: int) -> str:
    digest = hashlib.sha256()
    total = 0
    try:
        file_obj.seek(0)
        while True:
            chunk = file_obj.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise PlatformAppReleaseError(f"APK file exceeds max size {max_bytes}")
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        file_obj.seek(0)


def _release_object_key(platform: str, package_name: str, sha256: str) -> str:
    return f"platform-apps/{platform}/{package_name}/{sha256}.apk"


def _ensure_facebook_metadata(metadata: ApkMetadata) -> None:
    if metadata.package_name != FACEBOOK_PACKAGE:
        raise PlatformAppReleaseError(f"Only {FACEBOOK_PACKAGE} APK is accepted")


async def create_platform_app_release(
    db: AsyncSession,
    *,
    platform: str,
    content: bytes,
    filename: str | None,
    uploaded_by_user_id: str | None,
    notes: str | None = None,
) -> PlatformAppRelease:
    return await create_platform_app_release_from_file(
        db,
        platform=platform,
        file_obj=BytesIO(content),
        filename=filename,
        uploaded_by_user_id=uploaded_by_user_id,
        notes=notes,
    )


async def create_platform_app_release_from_file(
    db: AsyncSession,
    *,
    platform: str,
    file_obj: BinaryIO,
    filename: str | None,
    uploaded_by_user_id: str | None,
    notes: str | None = None,
) -> PlatformAppRelease:
    platform = platform.strip().lower()
    if platform != FACEBOOK_PLATFORM:
        raise PlatformAppReleaseError("Only facebook platform is supported")
    size_bytes = await asyncio.to_thread(_file_size, file_obj)
    if size_bytes <= 0:
        raise PlatformAppReleaseError("APK file is empty")
    max_bytes = _max_apk_bytes()
    if size_bytes > max_bytes:
        raise PlatformAppReleaseError(f"APK file exceeds max size {max_bytes}")
    if not minio_store.enabled():
        raise PlatformAppStorageUnavailable("Object storage is not configured")

    metadata = await asyncio.to_thread(parse_apk_metadata_from_file, file_obj)
    _ensure_facebook_metadata(metadata)
    sha256 = await asyncio.to_thread(_sha256_file, file_obj, max_bytes=max_bytes)
    object_key = _release_object_key(platform, metadata.package_name, sha256)

    existing = (
        await db.execute(
            select(PlatformAppRelease).where(
                PlatformAppRelease.platform == platform,
                PlatformAppRelease.package_name == metadata.package_name,
                PlatformAppRelease.sha256 == sha256,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    uploaded = await asyncio.to_thread(
        minio_store.upload_file,
        file_obj,
        object_key,
        length=size_bytes,
        content_type=APK_CONTENT_TYPE,
    )
    if not uploaded:
        raise PlatformAppUploadFailed("APK upload failed")

    row = PlatformAppRelease(
        platform=platform,
        package_name=metadata.package_name,
        version_name=metadata.version_name,
        version_code=metadata.version_code,
        sha256=sha256,
        size_bytes=size_bytes,
        object_key=object_key,
        original_filename=(filename or "").strip() or None,
        content_type_mime=APK_CONTENT_TYPE,
        status="draft",
        notes=(notes or "").strip() or None,
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.add(row)
    await db.flush()
    return row


async def list_platform_app_releases(
    db: AsyncSession,
    *,
    platform: str,
    offset: int = 0,
    limit: int = 50,
    status: str | None = None,
) -> tuple[list[PlatformAppRelease], int]:
    platform = platform.strip().lower()
    stmt = select(PlatformAppRelease).where(PlatformAppRelease.platform == platform)
    count_stmt = select(func.count()).select_from(PlatformAppRelease).where(
        PlatformAppRelease.platform == platform
    )
    if status:
        stmt = stmt.where(PlatformAppRelease.status == status)
        count_stmt = count_stmt.where(PlatformAppRelease.status == status)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(PlatformAppRelease.created_at.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 100)))
        )
    ).scalars().all()
    return list(rows), total


async def get_platform_app_release(db: AsyncSession, release_id: str) -> PlatformAppRelease | None:
    return await db.get(PlatformAppRelease, release_id)


async def get_active_platform_app_release(
    db: AsyncSession,
    *,
    platform: str,
    package_name: str = FACEBOOK_PACKAGE,
) -> PlatformAppRelease | None:
    return (
        await db.execute(
            select(PlatformAppRelease).where(
                PlatformAppRelease.platform == platform.strip().lower(),
                PlatformAppRelease.package_name == package_name,
                PlatformAppRelease.status == "active",
            )
        )
    ).scalar_one_or_none()


async def publish_platform_app_release(
    db: AsyncSession,
    *,
    release_id: str,
) -> PlatformAppRelease:
    row = await get_platform_app_release(db, release_id)
    if row is None:
        raise PlatformAppReleaseError("Release not found")
    if row.status == "archived":
        raise PlatformAppReleaseError("Archived release cannot be published")
    now = _utcnow()
    await db.execute(
        update(PlatformAppRelease)
        .where(PlatformAppRelease.platform == row.platform)
        .where(PlatformAppRelease.package_name == row.package_name)
        .where(PlatformAppRelease.status == "active")
        .where(PlatformAppRelease.id != row.id)
        .values(status="archived", archived_at=now, updated_at=now)
    )
    row.status = "active"
    row.published_at = now
    row.archived_at = None
    row.updated_at = now
    await db.flush()
    return row


async def archive_platform_app_release(
    db: AsyncSession,
    *,
    release_id: str,
) -> PlatformAppRelease:
    row = await get_platform_app_release(db, release_id)
    if row is None:
        raise PlatformAppReleaseError("Release not found")
    now = _utcnow()
    row.status = "archived"
    row.archived_at = now
    row.updated_at = now
    await db.flush()
    return row


def release_download_url(row: PlatformAppRelease, *, expires_seconds: int = 3600) -> str | None:
    return minio_store.presigned_get(row.object_key, expires_seconds=expires_seconds)


def release_object_bytes(row: PlatformAppRelease) -> bytes | None:
    return minio_store.get_object_bytes(row.object_key)


def iter_release_object_bytes(row: PlatformAppRelease) -> Iterator[bytes] | None:
    return minio_store.iter_object_bytes(row.object_key)


def release_to_dict(row: PlatformAppRelease) -> dict[str, Any]:
    return {
        "id": row.id,
        "platform": row.platform,
        "package_name": row.package_name,
        "version_name": row.version_name,
        "version_code": row.version_code,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "object_key": row.object_key,
        "original_filename": row.original_filename,
        "content_type_mime": row.content_type_mime,
        "status": row.status,
        "notes": row.notes,
        "uploaded_by_user_id": row.uploaded_by_user_id,
        "published_at": row.published_at,
        "archived_at": row.archived_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
