from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import _get_current_user, _get_db
from api.routes.content import router as content_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(content_router, prefix="/api")

    async def _db_override():
        yield AsyncMock()

    async def _user_override():
        return SimpleNamespace(id="user-1", role="user", is_active=True)

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


def _fake_item():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id="item-1",
        collection="fb_group",
        platform="facebook",
        content_type="post",
        title="",
        body="hello world",
        author="author-1",
        url="https://example.com/post",
        likes_count=10,
        comments_count=2,
        shares_count=1,
        views_count=100,
        tags="tag1,tag2",
        device_serial="serial-1",
        campaign_id="camp-1",
        execution_id="exec-1",
        extracted_at=now,
        content_hash="hash-1",
        parent_id=None,
        item_level="post",
        author_id="author-id",
        scenario_name="fb_group_1h",
        content_date=now,
        created_at=now,
    )


@pytest.mark.asyncio
async def test_list_content_forwards_filters_and_user_id():
    app = _build_app()
    fake_item = _fake_item()
    with patch("api.routes.content.content_crud.query_content", new=AsyncMock(return_value=([fake_item], 1))) as mock_query:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/content",
                params={
                    "collection": "fb_group",
                    "platform": "facebook",
                    "content_type": "post",
                    "search": "openclaw",
                    "device_serial": "serial-1",
                    "campaign_id": "camp-1",
                    "execution_id": "exec-1",
                    "content_hash": "hash-1",
                    "parent_id": "parent-1",
                    "limit": 20,
                    "offset": 10,
                },
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    kwargs = mock_query.await_args.kwargs
    assert kwargs["user_id"] == "user-1"
    assert kwargs["execution_id"] == "exec-1"
    assert kwargs["parent_id"] == "parent-1"
    assert kwargs["limit"] == 20
    assert kwargs["offset"] == 10


@pytest.mark.asyncio
async def test_stream_export_csv_returns_attachment_and_rows():
    app = _build_app()
    fake_item = _fake_item()
    with patch(
        "api.routes.content.content_crud.query_content",
        new=AsyncMock(side_effect=[([fake_item], 1), ([], 1)]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/content/export/stream", params={"format": "csv"})
    assert resp.status_code == 200
    assert "attachment; filename=\"content-export.csv\"" in resp.headers.get("content-disposition", "")
    payload = resp.text
    assert "id,collection,platform" in payload
    assert "item-1,fb_group,facebook" in payload


@pytest.mark.asyncio
async def test_download_export_enforces_ready_and_file_exists():
    app = _build_app()
    with patch(
        "api.routes.content.content_crud.get_export",
        new=AsyncMock(return_value=SimpleNamespace(status="processing", file_path=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            not_ready = await ac.get("/api/content/exports/export-1/download")
    assert not_ready.status_code == 422
    assert "Export not ready" in not_ready.json()["detail"]

    with (
        patch(
            "api.routes.content.content_crud.get_export",
            new=AsyncMock(return_value=SimpleNamespace(status="ready", file_path="/tmp/not-found.csv", format="csv")),
        ),
        patch("api.routes.content.os.path.exists", return_value=False),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            missing = await ac.get("/api/content/exports/export-2/download")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Export file not found on disk"
