"""Shared helpers for tenancy / cross-tenant HTTP tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.auth.rbac import _load_seed_policy_rows, clear_rbac_cache
from api.deps import _get_current_user, _get_db
from api.crud.router import api_router
from db.database import Base
from db.models import Organization, OrganizationMember, User
from db.models.campaign import Campaign
from db.models.device import Device
from tenancy.context import set_current_org_id


ORG_A = "org-acme"
ORG_B = "org-beta"
USER_A = "user-alice"
USER_B = "user-bob"
PASS = "secret123"


async def seed_casbin_policy_tables(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS casbin_policy_revision (
                id INTEGER PRIMARY KEY,
                revision INTEGER NOT NULL
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            INSERT INTO casbin_policy_revision (id, revision)
            VALUES (1, 1)
            ON CONFLICT(id) DO UPDATE SET revision = excluded.revision
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS casbin_rule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ptype VARCHAR(32) NOT NULL,
                v0 VARCHAR(255),
                v1 VARCHAR(255),
                v2 VARCHAR(255),
                v3 VARCHAR(255),
                v4 VARCHAR(255),
                v5 VARCHAR(255)
            )
            """
        )
    )
    await conn.execute(text("DELETE FROM casbin_rule"))
    for row in _load_seed_policy_rows():
        padded = list(row[:7]) + [""] * max(0, 7 - len(row))
        await conn.execute(
            text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, v4, v5)
                VALUES (:ptype, :v0, :v1, :v2, :v3, :v4, :v5)
                """
            ),
            {
                "ptype": padded[0],
                "v0": padded[1],
                "v1": padded[2],
                "v2": padded[3],
                "v3": padded[4],
                "v4": padded[5],
                "v5": padded[6],
            },
        )
    clear_rbac_cache()


@pytest_asyncio.fixture
async def tenancy_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await seed_casbin_policy_tables(conn)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def tenancy_session_factory(tenancy_engine):
    return async_sessionmaker(
        tenancy_engine, expire_on_commit=False, class_=AsyncSession
    )


def build_tenancy_api_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    async def _db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[_get_db] = _db_override
    return app


def user_override_factory(user_id: str, org_id: str):
    async def _override():
        set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@example.com",
            name=user_id,
            role="operator",
            is_active=True,
            org_id=org_id,
        )

    return _override


async def seed_two_org_fixture(session_factory) -> dict[str, Any]:
    """Two orgs, two users, devices + campaigns in each org."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        org_a = Organization(
            id=ORG_A,
            business_name="Acme",
            business_email="acme@example.com",
            status="active",
            plan="standard",
            created_at=now,
        )
        org_b = Organization(
            id=ORG_B,
            business_name="Beta",
            business_email="beta@example.com",
            status="active",
            plan="standard",
            created_at=now,
        )
        user_a = User(
            id=USER_A,
            email="alice@acme.example",
            name="Alice",
            hashed_password="hashed",
            org_id=ORG_A,
        )
        user_b = User(
            id=USER_B,
            email="bob@beta.example",
            name="Bob",
            hashed_password="hashed",
            org_id=ORG_B,
        )
        session.add_all([org_a, org_b, user_a, user_b])
        await session.flush()
        session.add_all(
            [
                OrganizationMember(
                    id="mem-a",
                    organization_id=ORG_A,
                    user_id=USER_A,
                    role="owner",
                    created_at=now,
                ),
                OrganizationMember(
                    id="mem-b",
                    organization_id=ORG_B,
                    user_id=USER_B,
                    role="owner",
                    created_at=now,
                ),
            ]
        )
        devices_a = [
            Device(
                id=f"dev-a-{i}",
                serial=f"ACME-{i}",
                name=f"Acme device {i}",
                user_id=USER_A,
                org_id=ORG_A,
                created_at=now,
            )
            for i in range(1, 6)
        ]
        devices_b = [
            Device(
                id=f"dev-b-{i}",
                serial=f"BETA-{i}",
                name=f"Beta device {i}",
                user_id=USER_B,
                org_id=ORG_B,
                created_at=now,
            )
            for i in range(1, 4)
        ]
        session.add_all(devices_a + devices_b)
        session.add_all(
            [
                Campaign(
                    id="camp-a-1",
                    name="Acme campaign",
                    user_id=USER_A,
                    org_id=ORG_A,
                    created_at=now,
                    updated_at=now,
                ),
                Campaign(
                    id="camp-b-1",
                    name="Beta campaign",
                    user_id=USER_B,
                    org_id=ORG_B,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.commit()

    return {
        "org_a": ORG_A,
        "org_b": ORG_B,
        "user_a": USER_A,
        "user_b": USER_B,
        "device_a_ids": [f"dev-a-{i}" for i in range(1, 6)],
        "device_b_ids": [f"dev-b-{i}" for i in range(1, 4)],
        "device_b_first": "dev-b-1",
        "campaign_a": "camp-a-1",
        "campaign_b": "camp-b-1",
    }


def api_client_for_user(app: FastAPI, user_id: str, org_id: str) -> AsyncClient:
    app.dependency_overrides[_get_current_user] = user_override_factory(user_id, org_id)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
