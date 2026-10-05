"""E2E-style API flow for token-protected content permalinks (TC-DF-T-11-010-07)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.auth.content_share import create_content_share_token
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
        collection="platform_collection",
        platform="instagram",
        content_type="ig_media",
        title="Title",
        body="body",
        author="author",
        author_id="a1",
        url="https://example.com/p",
        likes_count=1,
        comments_count=2,
        shares_count=0,
        views_count=0,
        tags="",
        device_serial="serial-1",
        campaign_id="camp-1",
        execution_id=None,
        extracted_at=now,
        content_hash="hash-1",
        parent_id=None,
        item_level=0,
        scenario_name="scn",
        content_date=now,
        created_at=now,
        media_urls=[],
        screenshot_path=None,
        raw_data={"hierarchy_xml": "<h/>"},
    )


@pytest.mark.asyncio
async def test_permalink_flow_create_then_access_with_share_token():
    """Operator copies permalink; recipient opens detail with ?share= after auth."""
    app = _build_app()
    fake_item = _fake_item()
    token = create_content_share_token(user_id="user-1", content_id="item-1")

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
            create = await ac.post("/api/content/item-1/permalink")
            assert create.status_code == 200
            assert "share=" in create.json()["path"]

            detail = await ac.get("/api/content/item-1", params={"share": token})
            assert detail.status_code == 200
            body = detail.json()
            assert body["id"] == "item-1"
            assert body["payload"]["body"] == "body"
            assert any(a["id"] == "inline:hierarchy_xml" for a in body["artifacts"])


@pytest.mark.asyncio
async def test_permalink_flow_wrong_content_id_in_token_rejected():
    app = _build_app()
    token = create_content_share_token(user_id="user-1", content_id="other-item")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/content/item-1", params={"share": token})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_permalink_flow_download_requires_valid_share_when_using_share_link():
    app = _build_app()
    fake_item = _fake_item()
    token = create_content_share_token(user_id="user-1", content_id="item-1")

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
            ok = await ac.get(
                "/api/content/item-1/artifacts/inline:hierarchy_xml/download",
                params={"share": token},
            )
            bad = await ac.get(
                "/api/content/item-1/artifacts/inline:hierarchy_xml/download",
                params={"share": "not-a-jwt"},
            )
    assert ok.status_code == 200
    assert bad.status_code == 403
