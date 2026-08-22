"""Phase 1 of the connection workflow: dedupe, pacing, and platform neutrality.

Covers the three gaps that let an account send friend requests forever without
gaining friends: on-screen sends never reaching the candidate pipeline, no rate
budget at all, and every account in an organisation approaching the same people.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.database import Base
from db.models import Account, ExternalEntity, Organization, User
from db.models.facebook_candidate import SocialCandidate
from services.facebook_candidates import lease_next_ready_candidate
from services.social_candidates import (
    record_connection_request,
    requested_status_for,
)
from services.social_identity import profile_identity_key
from tenancy.context import set_current_org_id

ORG = "org-pipeline"
USER = "user-pipeline"
ACCOUNT_1 = "account-pipeline-1"
ACCOUNT_2 = "account-pipeline-2"


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    async with factory() as db:
        db.add_all(
            [
                Organization(
                    id=ORG,
                    business_name="Pipeline Org",
                    business_email="pipeline@example.com",
                    status="active",
                    plan="standard",
                    created_at=now,
                ),
                User(
                    id=USER,
                    email="pipeline@example.com",
                    name="Pipeline",
                    hashed_password="hashed",
                    org_id=ORG,
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                Account(
                    id=ACCOUNT_1,
                    org_id=ORG,
                    platform="facebook",
                    username="pipeline-1",
                ),
                Account(
                    id=ACCOUNT_2,
                    org_id=ORG,
                    platform="facebook",
                    username="pipeline-2",
                ),
            ]
        )
        await db.commit()
    set_current_org_id(ORG)
    yield factory
    set_current_org_id(None)
    await engine.dispose()


async def _ready_candidate(
    db: AsyncSession,
    *,
    account_id: str,
    entity_id: str,
    display_name: str,
    score: float = 0.9,
) -> SocialCandidate:
    now = datetime.now(UTC)
    db.add(
        ExternalEntity(
            id=entity_id,
            org_id=ORG,
            platform="facebook",
            entity_type="profile",
            identity_key=f"key-{entity_id}",
            display_name=display_name,
            status="candidate",
        )
    )
    await db.flush()
    candidate = SocialCandidate(
        id=f"cand-{account_id}-{entity_id}",
        org_id=ORG,
        account_id=account_id,
        platform="facebook",
        external_entity_id=entity_id,
        status="ready_to_connect",
        final_score=score,
        first_observed_at=now,
        last_observed_at=now,
    )
    db.add(candidate)
    await db.flush()
    return candidate


# ── Recording on-screen sends ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recording_a_send_creates_entity_and_candidate(session_factory):
    async with session_factory() as db:
        record = await record_connection_request(
            db,
            org_id=ORG,
            account_id=ACCOUNT_1,
            platform="facebook",
            display_name="Nguyễn Thùy Trang",
        )
        await db.commit()

    assert record["created"] is True
    assert record["status"] == "request_pending"
    assert record["identity_confidence"] == "name_only"

    async with session_factory() as db:
        candidate = (
            await db.execute(
                select(SocialCandidate).where(SocialCandidate.org_id == ORG)
            )
        ).scalar_one()
        assert candidate.status == "request_pending"
        assert candidate.platform == "facebook"
        assert candidate.requested_at is not None


@pytest.mark.asyncio
async def test_recording_uses_the_same_identity_key_as_discovery(session_factory):
    """The UI scan and content-author discovery must converge on one row."""
    async with session_factory() as db:
        record = await record_connection_request(
            db,
            org_id=ORG,
            account_id=ACCOUNT_1,
            platform="facebook",
            display_name="Lê Văn Cường",
        )
        await db.commit()

    from services.facebook_candidate_discovery import _identity_key
    from services.facebook_candidates import normalize_vietnamese_text

    assert record["identity_key"] == _identity_key(
        None, normalize_vietnamese_text("Lê Văn Cường")
    )


@pytest.mark.asyncio
async def test_recorded_person_is_not_leased_again(session_factory):
    async with session_factory() as db:
        await _ready_candidate(
            db,
            account_id=ACCOUNT_1,
            entity_id="entity-lease-1",
            display_name="Pham Van D",
        )
        await db.commit()

    # Same person reached through the on-screen scan instead of the lease.
    async with session_factory() as db:
        entity = (
            await db.execute(
                select(ExternalEntity).where(ExternalEntity.id == "entity-lease-1")
            )
        ).scalar_one()
        candidate = (
            await db.execute(
                select(SocialCandidate).where(
                    SocialCandidate.external_entity_id == entity.id
                )
            )
        ).scalar_one()
        candidate.status = "request_pending"
        candidate.requested_at = datetime.now(UTC)
        await db.commit()

    async with session_factory() as db:
        attempt = await lease_next_ready_candidate(
            db, org_id=ORG, account_id=ACCOUNT_1, execution_id="exec-1"
        )
        assert attempt.lease is None
        assert attempt.outcome == "no_ready_candidate"


@pytest.mark.asyncio
async def test_recording_twice_keeps_one_candidate(session_factory):
    async with session_factory() as db:
        first = await record_connection_request(
            db,
            org_id=ORG,
            account_id=ACCOUNT_1,
            platform="facebook",
            display_name="Trùng Tên",
        )
        second = await record_connection_request(
            db,
            org_id=ORG,
            account_id=ACCOUNT_1,
            platform="facebook",
            display_name="Trùng Tên",
        )
        await db.commit()

    assert first["candidate_id"] == second["candidate_id"]
    assert second["created"] is False


# ── Cross-account target exclusivity ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_sibling_account_skips_a_person_already_approached(session_factory):
    async with session_factory() as db:
        await _ready_candidate(
            db,
            account_id=ACCOUNT_1,
            entity_id="entity-shared",
            display_name="Shared Target",
        )
        # Same entity, second account in the same org — exactly what shared
        # org-scope discovery produces.
        now = datetime.now(UTC)
        db.add(
            SocialCandidate(
                id="cand-2-shared",
                org_id=ORG,
                account_id=ACCOUNT_2,
                platform="facebook",
                external_entity_id="entity-shared",
                status="ready_to_connect",
                final_score=0.95,
                first_observed_at=now,
                last_observed_at=now,
            )
        )
        await db.commit()

    async with session_factory() as db:
        first = await lease_next_ready_candidate(
            db, org_id=ORG, account_id=ACCOUNT_1, execution_id="exec-a"
        )
        assert first.lease is not None
        candidate = first.lease.candidate
        candidate.status = "request_pending"
        candidate.requested_at = datetime.now(UTC)
        await db.commit()

    async with session_factory() as db:
        second = await lease_next_ready_candidate(
            db, org_id=ORG, account_id=ACCOUNT_2, execution_id="exec-b"
        )
        assert second.lease is None


@pytest.mark.asyncio
async def test_sibling_guard_expires_after_the_cooldown(session_factory, monkeypatch):
    monkeypatch.setenv("SIBLING_TARGET_COOLDOWN_DAYS", "30")
    async with session_factory() as db:
        await _ready_candidate(
            db,
            account_id=ACCOUNT_2,
            entity_id="entity-old",
            display_name="Old Target",
        )
        stale = datetime.now(UTC) - timedelta(days=45)
        db.add(
            SocialCandidate(
                id="cand-1-old",
                org_id=ORG,
                account_id=ACCOUNT_1,
                platform="facebook",
                external_entity_id="entity-old",
                status="request_pending",
                requested_at=stale,
                first_observed_at=stale,
                last_observed_at=stale,
                updated_at=stale,
            )
        )
        await db.commit()

    async with session_factory() as db:
        attempt = await lease_next_ready_candidate(
            db, org_id=ORG, account_id=ACCOUNT_2, execution_id="exec-c"
        )
        assert attempt.lease is not None


@pytest.mark.asyncio
async def test_sibling_guard_can_be_disabled(session_factory, monkeypatch):
    monkeypatch.setenv("SIBLING_TARGET_COOLDOWN_DAYS", "0")
    async with session_factory() as db:
        await _ready_candidate(
            db,
            account_id=ACCOUNT_2,
            entity_id="entity-nolimit",
            display_name="Unguarded Target",
        )
        now = datetime.now(UTC)
        db.add(
            SocialCandidate(
                id="cand-1-nolimit",
                org_id=ORG,
                account_id=ACCOUNT_1,
                platform="facebook",
                external_entity_id="entity-nolimit",
                status="request_pending",
                requested_at=now,
                first_observed_at=now,
                last_observed_at=now,
            )
        )
        await db.commit()

    async with session_factory() as db:
        attempt = await lease_next_ready_candidate(
            db, org_id=ORG, account_id=ACCOUNT_2, execution_id="exec-d"
        )
        assert attempt.lease is not None


# ── Platform neutrality ──────────────────────────────────────────────────────


def test_follow_platforms_skip_the_pending_state():
    """TikTok/Threads follows are unilateral — nothing to reconcile later."""
    assert requested_status_for("facebook") == "request_pending"
    assert requested_status_for("tiktok") == "connected"
    assert requested_status_for("threads") == "connected"
    # Unknown platforms take the cautious two-sided assumption.
    assert requested_status_for("mystery-network") == "request_pending"


def test_identity_keys_are_namespaced_per_platform():
    facebook = profile_identity_key("facebook", display_name="Nguyen Van A")
    tiktok = profile_identity_key("tiktok", display_name="Nguyen Van A")
    assert facebook != tiktok
    # Facebook keeps its historical prefix so stored keys keep matching.
    assert facebook.startswith("fb-profile:")
    assert tiktok.startswith("tiktok-profile:")


def test_identity_key_prefers_external_id_over_name():
    by_id = profile_identity_key("facebook", external_id="100", display_name="A")
    same_id_other_name = profile_identity_key(
        "facebook", external_id="100", display_name="B"
    )
    assert by_id == same_id_other_name


@pytest.mark.asyncio
async def test_recording_a_follow_lands_connected(session_factory):
    async with session_factory() as db:
        record = await record_connection_request(
            db,
            org_id=ORG,
            account_id=ACCOUNT_1,
            platform="tiktok",
            display_name="Creator X",
            external_id="tt-123",
        )
        await db.commit()

    assert record["status"] == "connected"
    assert record["identity_confidence"] == "external_id"


# ── Migration ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_113_backfills_existing_rows():
    """Existing candidate rows predate multi-platform and are all Facebook."""
    import importlib

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    migration = importlib.import_module(
        "db.migrations.113_social_candidates_platform"
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            # Legacy shape: no platform, no requested_at.
            await conn.execute(
                text(
                    "CREATE TABLE facebook_candidates ("
                    "id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), "
                    "account_id VARCHAR(36), external_entity_id VARCHAR(36), "
                    "status VARCHAR(32), updated_at TIMESTAMP)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO facebook_candidates VALUES "
                    "('c1','o1','a1','e1','request_pending','2026-01-01 00:00:00'),"
                    "('c2','o1','a1','e2','ready_to_connect','2026-01-02 00:00:00')"
                )
            )

            await migration.upgrade(conn)

            rows = (
                await conn.execute(
                    text(
                        "SELECT id, platform, requested_at FROM facebook_candidates "
                        "ORDER BY id"
                    )
                )
            ).all()

        assert [row[0] for row in rows] == ["c1", "c2"], "no row may be lost"
        assert all(row[1] == "facebook" for row in rows)
        # Only rows already awaiting a reply get a backfilled request time.
        assert rows[0][2] is not None
        assert rows[1][2] is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_113_is_idempotent():
    import importlib

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    migration = importlib.import_module(
        "db.migrations.113_social_candidates_platform"
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE facebook_candidates ("
                    "id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), "
                    "account_id VARCHAR(36), external_entity_id VARCHAR(36), "
                    "status VARCHAR(32), updated_at TIMESTAMP)"
                )
            )
            await migration.upgrade(conn)
            await migration.upgrade(conn)
    finally:
        await engine.dispose()
