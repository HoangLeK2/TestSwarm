from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.content_artifacts import (
    collect_content_artifacts,
    collect_primary_content_artifacts,
    merge_execution_artifacts,
    read_artifact_bytes,
)


def _item(**overrides):
    now = datetime.now(timezone.utc)
    base = dict(
        id="item-1",
        screenshot_path="https://cdn.example/screenshot.png",
        raw_data={
            "hierarchy_xml": "<hierarchy><node /></hierarchy>",
            "ocr_text": "hello",
        },
        extracted_at=now,
        created_at=now,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_collect_primary_content_artifacts_skips_screenshot_by_default(monkeypatch):
    monkeypatch.delenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", raising=False)
    arts = collect_primary_content_artifacts(_item())
    assert len(arts) == 1
    ids = {a["id"] for a in arts}
    assert ids == {"inline:hierarchy_xml"}


def test_collect_primary_content_artifacts_can_include_screenshot(monkeypatch):
    monkeypatch.setenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", "1")
    arts = collect_primary_content_artifacts(_item())
    assert len(arts) == 2
    ids = {a["id"] for a in arts}
    assert ids == {"screenshot", "inline:hierarchy_xml"}


def test_collect_content_artifacts_matches_primary():
    assert collect_content_artifacts(_item()) == collect_primary_content_artifacts(_item())


@pytest.mark.asyncio
async def test_read_inline_artifact_bytes():
    item = _item()
    payload, filename, mime = await read_artifact_bytes(item, "inline:hierarchy_xml")
    assert b"<hierarchy>" in payload
    assert "content_item-1" in filename
    assert mime == "application/xml"


@pytest.mark.asyncio
async def test_content_store_skips_screenshot_path_by_default(monkeypatch):
    from services.content_store import _resolve_content_screenshot_path

    monkeypatch.delenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", raising=False)
    path = await _resolve_content_screenshot_path(
        None,
        payload={"screenshot_path": "https://cdn.example/screenshot.png"},
        execution_id=None,
        screenshot_bytes=b"jpeg",
        content_hash="hash",
    )
    assert path is None


def test_save_screenshot_requires_object_storage_without_debug_fallback(monkeypatch):
    from services import minio_store
    from services.content_store import _save_screenshot

    monkeypatch.setenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", "1")
    monkeypatch.setattr(minio_store, "is_quality_ok", lambda _data: True)
    monkeypatch.setattr(minio_store, "enabled", lambda: False)
    monkeypatch.setattr(minio_store, "local_image_fallback_enabled", lambda: False)

    with pytest.raises(RuntimeError, match="local fallback disabled"):
        _save_screenshot(b"jpeg-bytes", "abcdef1234567890")


def test_save_screenshot_uses_image_hash_object_key(monkeypatch):
    from services import minio_store
    from services.content_store import _save_screenshot

    uploaded: dict[str, str] = {}
    data = b"same-image-bytes"
    expected_digest = hashlib.sha256(data).hexdigest()[:32]

    monkeypatch.setenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", "1")
    monkeypatch.setattr(minio_store, "is_quality_ok", lambda _data: True)
    monkeypatch.setattr(minio_store, "enabled", lambda: True)

    def fake_upload(_data: bytes, object_name: str):
        uploaded["object_name"] = object_name
        return f"https://cdn.example/{object_name}"

    monkeypatch.setattr(minio_store, "upload", fake_upload)

    first = _save_screenshot(data, "content-hash-a")
    second = _save_screenshot(data, "content-hash-b")

    assert first == second
    assert uploaded["object_name"] == f"content-screenshots/{expected_digest}.jpg"


@pytest.mark.asyncio
async def test_attach_screenshots_dedupes_upload_and_bulk_updates(monkeypatch):
    import db.crud.content as crud_content
    import db.database as database
    from services import minio_store
    from services.content_store import attach_screenshot_to_content_hashes

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            pass

    upload_calls: list[str] = []
    update_calls: list[list[str]] = []

    monkeypatch.setenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", "1")
    monkeypatch.setattr(database, "activity_session", lambda: FakeSession())
    monkeypatch.setattr(minio_store, "is_quality_ok", lambda _data: True)
    monkeypatch.setattr(minio_store, "enabled", lambda: True)

    def fake_upload(_data: bytes, object_name: str, content_type: str = "image/jpeg"):
        upload_calls.append(object_name)
        return f"https://cdn.example/{object_name}"

    async def fake_update_paths(_db, **kwargs):
        update_calls.append(list(kwargs["content_hashes"]))
        return len(kwargs["content_hashes"])

    monkeypatch.setattr(minio_store, "upload", fake_upload)
    monkeypatch.setattr(crud_content, "update_content_screenshot_paths", fake_update_paths)

    updated = await attach_screenshot_to_content_hashes(
        content_hashes=[f"hash-{i}" for i in range(25)],
        collection="posts",
        screenshot_bytes=b"same-image-bytes",
        execution_id="exec-1",
        only_if_missing=True,
    )

    assert updated == 25
    assert len(upload_calls) == 1
    assert len(update_calls) == 1
    assert len(update_calls[0]) == 25


def test_merge_execution_artifacts_skips_screenshot_by_default(monkeypatch):
    monkeypatch.delenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", raising=False)
    merged = merge_execution_artifacts(
        _item(),
        [],
        [("post.screenshot", "/artifacts/art-1/content")],
    )
    assert merged == []


def test_merge_execution_artifacts_marks_screenshot_proxy_as_image(monkeypatch):
    monkeypatch.setenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", "1")
    item = _item()
    merged = merge_execution_artifacts(
        item,
        [],
        [("post.screenshot", "/artifacts/art-1/content")],
    )
    assert len(merged) == 1
    assert merged[0]["kind"] == "image"
    assert merged[0]["mime_type"] == "image/png"


def test_merge_execution_artifacts_skips_duplicate_screenshot_and_hierarchy():
    item = _item()
    base = collect_content_artifacts(item)
    merged = merge_execution_artifacts(
        item,
        base,
        [
            ("post.screenshot", "/artifacts/art-1/content"),
            ("post.hierarchy", "/artifacts/art-2/content"),
        ],
    )
    assert merged == base
    assert len(merged) == 1


def test_inline_hierarchy_label_is_vietnamese():
    arts = collect_content_artifacts(_item())
    hierarchy = next(a for a in arts if a["id"] == "inline:hierarchy_xml")
    assert hierarchy["label"] == "XML giao diện"


@pytest.mark.asyncio
async def test_read_missing_artifact_raises():
    with pytest.raises(FileNotFoundError):
        await read_artifact_bytes(_item(), "missing")


@pytest.mark.asyncio
async def test_read_screenshot_uses_minio_not_http(monkeypatch):
    from services import content_artifacts, minio_store

    item = _item(
        screenshot_path="http://localhost:9000/device-farm/content-screenshots/abc123.jpg"
    )
    monkeypatch.setenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", "1")
    fetch_calls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        fetch_calls.append(url)
        raise AssertionError("should not HTTP-fetch object storage URLs")

    monkeypatch.setattr(content_artifacts, "_fetch_url_bytes", fake_fetch)
    monkeypatch.setattr(minio_store, "enabled", lambda: True)
    monkeypatch.setattr(
        minio_store,
        "get_object_bytes",
        lambda name: b"jpeg-bytes" if name == "content-screenshots/abc123.jpg" else None,
    )

    payload, filename, mime = await read_artifact_bytes(item, "screenshot")
    assert payload == b"jpeg-bytes"
    assert "content_" in filename
    assert mime.startswith("image/")
    assert fetch_calls == []


@pytest.mark.asyncio
async def test_read_screenshot_storage_miss_raises_without_http(monkeypatch):
    from services import content_artifacts, minio_store

    item = _item(
        screenshot_path="http://localhost:9000/device-farm/content-screenshots/missing.jpg"
    )
    monkeypatch.setenv("DEVICE_FARM_CONTENT_IMAGES_ENABLED", "1")
    monkeypatch.setattr(
        content_artifacts,
        "_fetch_url_bytes",
        lambda _url: (_ for _ in ()).throw(AssertionError("no http fallback")),
    )
    monkeypatch.setattr(minio_store, "get_object_bytes", lambda _name: None)

    with pytest.raises(FileNotFoundError):
        await read_artifact_bytes(item, "screenshot")
