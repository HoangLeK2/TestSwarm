from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.content_artifacts import collect_content_artifacts, read_artifact_bytes


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


def test_collect_content_artifacts_includes_screenshot_and_inline():
    arts = collect_content_artifacts(_item())
    ids = {a["id"] for a in arts}
    assert "screenshot" in ids
    assert "inline:hierarchy_xml" in ids
    assert "inline:ocr_text" in ids


@pytest.mark.asyncio
async def test_read_inline_artifact_bytes():
    item = _item()
    payload, filename, mime = await read_artifact_bytes(item, "inline:hierarchy_xml")
    assert b"<hierarchy>" in payload
    assert "content_item-1" in filename
    assert mime == "application/xml"


@pytest.mark.asyncio
async def test_read_missing_artifact_raises():
    with pytest.raises(FileNotFoundError):
        await read_artifact_bytes(_item(), "missing")
