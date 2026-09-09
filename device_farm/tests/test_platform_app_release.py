from __future__ import annotations

import struct
import zipfile
from io import BytesIO

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.database import Base
from services import platform_app_release as service


def _u8_len(value: int) -> bytes:
    if value > 0x7F:
        return bytes([0x80 | (value >> 8), value & 0xFF])
    return bytes([value])


def _string_pool(strings: list[str]) -> bytes:
    offsets: list[int] = []
    data = bytearray()
    for value in strings:
        raw = value.encode("utf-8")
        offsets.append(len(data))
        data.extend(_u8_len(len(value)))
        data.extend(_u8_len(len(raw)))
        data.extend(raw)
        data.append(0)
    header_size = 28
    strings_start = header_size + len(strings) * 4
    chunk_size = strings_start + len(data)
    return (
        struct.pack("<HHI", 0x0001, header_size, chunk_size)
        + struct.pack("<IIIII", len(strings), 0, 0x00000100, strings_start, 0)
        + b"".join(struct.pack("<I", offset) for offset in offsets)
        + bytes(data)
    )


def _start_tag(strings: list[str], attrs: dict[str, str | int]) -> bytes:
    attr_items = list(attrs.items())
    chunk_size = 36 + len(attr_items) * 20
    out = bytearray()
    out.extend(struct.pack("<HHI", 0x0102, 16, chunk_size))
    out.extend(struct.pack("<IIIIHHHHHH", 1, 0xFFFFFFFF, 0xFFFFFFFF, strings.index("manifest"), 20, 20, len(attr_items), 0, 0, 0))
    for name, value in attr_items:
        if isinstance(value, int):
            out.extend(
                struct.pack(
                    "<IIIHBBI",
                    0xFFFFFFFF,
                    strings.index(name),
                    0xFFFFFFFF,
                    8,
                    0,
                    0x10,
                    value,
                )
            )
        else:
            out.extend(
                struct.pack(
                    "<IIIHBBI",
                    0xFFFFFFFF,
                    strings.index(name),
                    strings.index(value),
                    8,
                    0,
                    0x03,
                    strings.index(value),
                )
            )
    return bytes(out)


def _apk(package_name: str = service.FACEBOOK_PACKAGE, version_name: str = "499.0.0.1.80", version_code: int = 499001080) -> bytes:
    strings = [
        "manifest",
        "package",
        "versionName",
        "versionCode",
        package_name,
        version_name,
    ]
    body = _string_pool(strings) + _start_tag(
        strings,
        {
            "package": package_name,
            "versionName": version_name,
            "versionCode": version_code,
        },
    )
    manifest = struct.pack("<HHI", 0x0003, 8, len(body) + 8) + body
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("AndroidManifest.xml", manifest)
        zf.writestr("classes.dex", b"dex\n")
    return buf.getvalue()


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


def test_parse_apk_metadata_from_binary_manifest():
    metadata = service.parse_apk_metadata(_apk())

    assert metadata.package_name == service.FACEBOOK_PACKAGE
    assert metadata.version_name == "499.0.0.1.80"
    assert metadata.version_code == "499001080"


def test_parse_apk_metadata_does_not_scan_full_archive(monkeypatch):
    def fail_testzip(_self):
        raise AssertionError("testzip scans every APK entry")

    monkeypatch.setattr(zipfile.ZipFile, "testzip", fail_testzip)

    metadata = service.parse_apk_metadata(_apk())

    assert metadata.package_name == service.FACEBOOK_PACKAGE


@pytest.mark.asyncio
async def test_create_release_rejects_non_facebook_package(monkeypatch, session_factory):
    monkeypatch.setattr(service.minio_store, "enabled", lambda: True)

    async with session_factory() as db:
        with pytest.raises(service.PlatformAppReleaseError, match=service.FACEBOOK_PACKAGE):
            await service.create_platform_app_release(
                db,
                platform="facebook",
                content=_apk(package_name="com.facebook.lite"),
                filename="facebook-lite.apk",
                uploaded_by_user_id=None,
            )


@pytest.mark.asyncio
async def test_create_release_uploads_from_seekable_file(monkeypatch, session_factory):
    apk = _apk()
    captured: dict[str, object] = {}
    monkeypatch.setattr(service.minio_store, "enabled", lambda: True)

    def upload_file(file_obj, object_key, *, length, content_type):
        captured["object_key"] = object_key
        captured["length"] = length
        captured["content_type"] = content_type
        captured["first_bytes"] = file_obj.read(2)
        return "https://cdn.example/apk"

    monkeypatch.setattr(service.minio_store, "upload_file", upload_file)

    async with session_factory() as db:
        row = await service.create_platform_app_release_from_file(
            db,
            platform="facebook",
            file_obj=BytesIO(apk),
            filename="facebook.apk",
            uploaded_by_user_id=None,
        )

    assert row.size_bytes == len(apk)
    assert captured["length"] == len(apk)
    assert captured["content_type"] == service.APK_CONTENT_TYPE
    assert captured["first_bytes"] == b"PK"
    assert str(captured["object_key"]).endswith(f"{row.sha256}.apk")


@pytest.mark.asyncio
async def test_publish_release_keeps_single_active(monkeypatch, session_factory):
    monkeypatch.setattr(service.minio_store, "enabled", lambda: True)
    monkeypatch.setattr(service.minio_store, "upload_file", lambda *_args, **_kwargs: "https://cdn.example/apk")

    async with session_factory() as db:
        first = await service.create_platform_app_release(
            db,
            platform="facebook",
            content=_apk(version_name="499.0.0.1.80", version_code=499001080),
            filename="facebook-499.apk",
            uploaded_by_user_id=None,
        )
        second = await service.create_platform_app_release(
            db,
            platform="facebook",
            content=_apk(version_name="500.0.0.1.90", version_code=500001090),
            filename="facebook-500.apk",
            uploaded_by_user_id=None,
        )

        await service.publish_platform_app_release(db, release_id=first.id)
        await service.publish_platform_app_release(db, release_id=second.id)
        await db.refresh(first)
        await db.refresh(second)

        assert first.status == "archived"
        assert second.status == "active"
        assert (await service.get_active_platform_app_release(db, platform="facebook")).id == second.id
