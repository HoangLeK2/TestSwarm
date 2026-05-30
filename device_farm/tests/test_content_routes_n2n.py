from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from api.deps import _get_current_user, _get_db
from api.routes.content import router as content_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(content_router, prefix="/api")

    async def _db_override():
        yield AsyncMock()

    async def _user_override():
        return SimpleNamespace(
            id="user-1",
            role="operator",
            org_role="owner",
            is_active=True,
            org_id="org-1",
        )

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
        item_level=0,
        author_id="author-id",
        scenario_name="fb_group_1h",
        content_date=now,
        created_at=now,
        media_urls=[],
        screenshot_path=None,
        raw_data={"hierarchy_xml": "<h/>"},
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
async def test_legacy_async_export_endpoints_removed():
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp_create = await ac.post("/api/content/export", json={"format": "csv"})
        resp_list = await ac.get("/api/content/exports/list")
        resp_get = await ac.get("/api/content/exports/export-1")
        resp_download = await ac.get("/api/content/exports/export-1/download")
    assert resp_create.status_code == 404
    assert resp_list.status_code == 404
    assert resp_get.status_code == 404
    assert resp_download.status_code == 404


@pytest.mark.asyncio
async def test_get_content_detail_includes_payload_and_artifacts():
    app = _build_app()
    fake_item = _fake_item()
    with (
        patch(
            "api.routes.content.content_crud.get_content_item",
            new=AsyncMock(return_value=fake_item),
        ),
        patch(
            "api.routes.content._execution_step_artifact_pairs",
            new=AsyncMock(return_value=[]),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/content/item-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "item-1"
    assert body["payload"]["body"] == "hello world"
    assert any(a["id"] == "inline:hierarchy_xml" for a in body["artifacts"])


@pytest.mark.asyncio
async def test_create_content_permalink_returns_token():
    app = _build_app()
    fake_item = _fake_item()
    with patch(
        "api.routes.content.content_crud.get_content_item",
        new=AsyncMock(return_value=fake_item),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/content/item-1/permalink")
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"].startswith("/dashboard/content/item-1?share=")
    assert body["token"]


@pytest.mark.asyncio
async def test_get_content_with_invalid_share_token_returns_403():
    app = _build_app()
    with patch(
        "api.routes.content.verify_content_share_token",
        side_effect=HTTPException(status_code=403, detail="bad"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/content/item-1", params={"share": "bad-token"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_download_inline_artifact():
    app = _build_app()
    fake_item = _fake_item()
    with (
        patch(
            "api.routes.content.content_crud.get_content_item",
            new=AsyncMock(return_value=fake_item),
        ),
        patch(
            "api.routes.content._execution_step_artifact_pairs",
            new=AsyncMock(return_value=[]),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/content/item-1/artifacts/inline:hierarchy_xml/download")
    assert resp.status_code == 200
    assert b"<h/>" in resp.content
    assert "attachment" in resp.headers.get("content-disposition", "")
