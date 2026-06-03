from __future__ import annotations

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
