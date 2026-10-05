"""Opt-in PostgreSQL schema and concurrency proof for AI Device Lab.

Run only against an empty, disposable database whose name starts with
``android_platform_tester_adl_e2e_``::

    AI_DEVICE_LAB_POSTGRES_E2E_URL=postgresql+asyncpg://.../android_platform_tester_adl_e2e_local \
      .venv/bin/python -m pytest tests/test_ai_lab_postgres_e2e.py -q
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db import models  # noqa: F401 - register all metadata before create_all
from db.database import (
    Base,
    _ensure_create_all_prerequisites,
    _ensure_legacy_migration_prerequisites,
)
from db.migrations import run_migrations
from db.models.ai_device_lab import ServiceCampaign, ServiceLane
from db.models.ai_device_lab_fleet import DeviceReservation
from db.models.campaign import Campaign
from db.models.device import Device
from db.models.organization import Organization, OrganizationMember
from tenancy.context import tenant_context

_POSTGRES_URL = os.getenv("AI_DEVICE_LAB_POSTGRES_E2E_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not _POSTGRES_URL,
    reason="AI_DEVICE_LAB_POSTGRES_E2E_URL is not configured",
)

ORG = "org-adl-pg-e2e"
USER = "user-adl-pg-e2e"
CAMPAIGN = "campaign-adl-pg-e2e"
SERVICE = "service-adl-pg-e2e"
DEVICE = "device-adl-pg-e2e"
LANES = ("lane-adl-pg-e2e-a", "lane-adl-pg-e2e-b")


def _validated_database_url() -> str:
    parsed = urlsplit(_POSTGRES_URL)
    database_name = parsed.path.lstrip("/").split("/", 1)[0]
    if not database_name.startswith("android_platform_tester_adl_e2e_"):
        raise RuntimeError(
            "PostgreSQL E2E requires a disposable database named "
            "android_platform_tester_adl_e2e_*"
        )
    url = make_url(_POSTGRES_URL)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        raise RuntimeError("PostgreSQL E2E requires the asyncpg driver")
    return url.render_as_string(hide_password=False)


async def _seed_race_fixture(factory: async_sessionmaker[AsyncSession]) -> None:
    now = datetime.now(UTC)
    async with factory() as session:
        session.add(Organization(id=ORG, business_name="ADL PostgreSQL E2E"))
        await session.flush()
        await session.execute(
            text(
                """
                INSERT INTO users (
                    id, email, name, hashed_password, api_key, role, is_active,
                    must_change_password, default_org_id, created_at,
                    failed_login_count, org_id
                ) VALUES (
                    :id, :email, :name, :password, :api_key, 'system', TRUE,
                    FALSE, :org_id, :created_at, 0, :org_id
                )
                """
            ),
            {
                "id": USER,
                "email": "adl-pg-e2e@example.invalid",
                "name": "ADL PostgreSQL E2E",
                "password": "disabled",
                "api_key": "adl-pg-e2e-disabled-api-key",
                "org_id": ORG,
                "created_at": now,
            },
        )
        session.add(
            OrganizationMember(
                id="member-adl-pg-e2e",
                organization_id=ORG,
                user_id=USER,
                role="owner",
            )
        )
        session.add(
            Campaign(
                id=CAMPAIGN,
                org_id=ORG,
                name="ADL PostgreSQL E2E",
                user_id=USER,
            )
        )
        session.add(
            Device(
                id=DEVICE,
                org_id=ORG,
                serial="ADL-PG-E2E-DEVICE",
                name="ADL PostgreSQL E2E device",
                user_id=USER,
            )
        )
        await session.flush()
        session.add(
            ServiceCampaign(
                id=SERVICE,
                org_id=ORG,
                runtime_campaign_id=CAMPAIGN,
                owner_id=USER,
                package_name="com.example.adl",
                timezone="UTC",
                plan_version="adl-pg-e2e-v1",
            )
        )
        await session.flush()
        session.add_all(
            [
                ServiceLane(
                    id=LANES[0],
                    org_id=ORG,
                    service_campaign_id=SERVICE,
                    ordinal=1,
                    tester_label="PG-A",
                ),
                ServiceLane(
                    id=LANES[1],
                    org_id=ORG,
                    service_campaign_id=SERVICE,
                    ordinal=2,
                    tester_label="PG-B",
                ),
            ]
        )
        await session.commit()


async def _race_reservation(
    factory: async_sessionmaker[AsyncSession],
    *,
    reservation_id: str,
    lane_id: str,
    start_gate: asyncio.Event,
    ready: asyncio.Event,
) -> str:
    starts_at = datetime(2026, 10, 5, tzinfo=UTC)
    with tenant_context(ORG):
        async with factory() as session:
            session.add(
                DeviceReservation(
                    id=reservation_id,
                    org_id=ORG,
                    service_campaign_id=SERVICE,
                    lane_id=lane_id,
                    device_id=DEVICE,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(days=14),
                    state="active",
                    created_by=USER,
                )
            )
            ready.set()
            await start_gate.wait()
            try:
                await session.commit()
                return "committed"
            except IntegrityError:
                await session.rollback()
                return "rejected"


async def _invalid_interval_rejected(
    factory: async_sessionmaker[AsyncSession],
) -> bool:
    observed_at = datetime(2026, 11, 1, tzinfo=UTC)
    with tenant_context(ORG):
        async with factory() as session:
            session.add(
                DeviceReservation(
                    id="reservation-adl-pg-invalid",
                    org_id=ORG,
                    service_campaign_id=SERVICE,
                    lane_id=LANES[1],
                    device_id=DEVICE,
                    starts_at=observed_at,
                    ends_at=observed_at,
                    state="active",
                    created_by=USER,
                )
            )
            try:
                await session.commit()
                return False
            except IntegrityError:
                await session.rollback()
                return True


@pytest.mark.asyncio
async def test_fresh_schema_is_idempotent_and_rejects_overlapping_reservation_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _validated_database_url()
    monkeypatch.setenv(
        "DEVICE_FARM_MCP_TOKEN_STORE",
        "/tmp/android_platform_tester_adl_e2e_no_legacy_tokens.json",
    )
    engine = create_async_engine(database_url, pool_size=3, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with engine.begin() as conn:
            existing_tables = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                        """
                    )
                )
            ).scalar_one()
            assert existing_tables == 0, "PostgreSQL E2E database must be empty"
            await _ensure_create_all_prerequisites(conn)
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
            await _ensure_legacy_migration_prerequisites(conn)
            await run_migrations(conn)

        # Reproduce pre-159 separately and prove the reconciliation queue can
        # be added without rebuilding existing billing history.
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE payment_reconciliation_jobs"))
            await conn.execute(
                text(
                    """
                    DELETE FROM schema_migrations
                    WHERE filename IN (
                        '159_ai_device_lab_payment_reconciliation.py',
                        '161_ai_device_lab_checkout_intent.py'
                    )
                    """
                )
            )
            await run_migrations(conn)

        async with engine.begin() as conn:
            await run_migrations(conn)

        # Reproduce pre-160 and prove the refund outbox plus tenant candidate
        # key can be added without rewriting existing refund records.
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE refund_dispatch_jobs"))
            await conn.execute(
                text(
                    "ALTER TABLE service_refunds "
                    "DROP CONSTRAINT uq_service_refunds_org_id"
                )
            )
            await conn.execute(
                text(
                    """
                    DELETE FROM schema_migrations
                    WHERE filename = '160_ai_device_lab_refund_dispatch.py'
                    """
                )
            )
            await run_migrations(conn)

        # Reproduce pre-161 and prove checkout intent/reconciliation metadata
        # can be introduced without rebuilding existing billing history.
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE payment_intents "
                    "DROP CONSTRAINT uq_payment_intents_order"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE payment_intents "
                    "DROP COLUMN last_error_code, "
                    "DROP COLUMN checkout_expires_at, "
                    "DROP COLUMN updated_at"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE payment_reconciliation_jobs "
                    "DROP COLUMN provider_lookup_key"
                )
            )
            await conn.execute(
                text(
                    """
                    DELETE FROM schema_migrations
                    WHERE filename = '161_ai_device_lab_checkout_intent.py'
                    """
                )
            )
            await run_migrations(conn)

        # Reproduce pre-162 and prove the append-only funnel ledger can be
        # added independently of existing campaign and billing history.
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE ai_lab_funnel_events"))
            await conn.execute(
                text(
                    """
                    DELETE FROM schema_migrations
                    WHERE filename = '162_ai_device_lab_funnel.py'
                    """
                )
            )
            await run_migrations(conn)

        # Reproduce a pre-157/pre-158 production schema so forward migrations,
        # rather than create_all, prove they can upgrade in place.
        async with engine.begin() as conn:
            await conn.execute(text("DROP INDEX idx_evidence_items_retention"))
            await conn.execute(text("DROP INDEX idx_farm_job_outbox_delivery"))
            await conn.execute(
                text("ALTER TABLE farm_job_outbox DROP COLUMN lease_token")
            )
            await conn.execute(
                text("ALTER TABLE farm_job_outbox DROP COLUMN delivered_at")
            )
            await conn.execute(
                text(
                    """
                    DELETE FROM schema_migrations
                    WHERE filename IN (
                        '157_ai_device_lab_evidence_retention.py',
                        '158_ai_device_lab_farm_outbox_lease.py'
                    )
                    """
                )
            )
            await run_migrations(conn)

        async with engine.connect() as conn:
            migration_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM schema_migrations
                        WHERE filename ~ '^(14[0-9]|15[0-9]|16[0-2]_)'
                        """
                    )
                )
            ).scalar_one()
            constraint_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_constraint
                        WHERE conname IN (
                            'uq_scenario_generation_operations_org_id',
                            'ex_device_reservation_overlap',
                            'chk_device_reservation_interval'
                        )
                        """
                    )
                )
            ).scalar_one()
            retention_index_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'idx_evidence_items_retention'
                        """
                    )
                )
            ).scalar_one()
            farm_outbox_column_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'farm_job_outbox'
                          AND column_name IN ('lease_token', 'delivered_at')
                        """
                    )
                )
            ).scalar_one()
            farm_outbox_index_is_leased = (
                await conn.execute(
                    text(
                        """
                        SELECT indexdef LIKE '%(status, available_at, lease_until)%'
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'idx_farm_job_outbox_delivery'
                        """
                    )
                )
            ).scalar_one()
            payment_reconciliation_table_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = 'payment_reconciliation_jobs'
                        """
                    )
                )
            ).scalar_one()
            payment_reconciliation_index_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'idx_payment_reconciliation_delivery'
                        """
                    )
                )
            ).scalar_one()
            refund_dispatch_table_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = 'refund_dispatch_jobs'
                        """
                    )
                )
            ).scalar_one()
            refund_dispatch_index_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'idx_refund_dispatch_delivery'
                        """
                    )
                )
            ).scalar_one()
            refund_tenant_constraint_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_constraint
                        WHERE conname = 'uq_service_refunds_org_id'
                        """
                    )
                )
            ).scalar_one()
            checkout_intent_column_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'payment_intents'
                          AND column_name IN (
                              'last_error_code',
                              'checkout_expires_at',
                              'updated_at'
                          )
                        """
                    )
                )
            ).scalar_one()
            checkout_intent_constraint_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_constraint
                        WHERE conname = 'uq_payment_intents_order'
                        """
                    )
                )
            ).scalar_one()
            reconciliation_lookup_column_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'payment_reconciliation_jobs'
                          AND column_name = 'provider_lookup_key'
                        """
                    )
                )
            ).scalar_one()
            funnel_table_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = 'ai_lab_funnel_events'
                        """
                    )
                )
            ).scalar_one()
            funnel_index_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'idx_ai_lab_funnel_campaign_time'
                        """
                    )
                )
            ).scalar_one()
            trigger_count = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_trigger
                        WHERE NOT tgisinternal AND tgname IN (
                            'app_builds_immutable', 'scenario_approvals_immutable',
                            'participation_events_immutable',
                            'device_hygiene_audits_immutable',
                            'reservation_audits_immutable', 'payment_events_immutable',
                            'readiness_checks_immutable',
                            'quota_ledger_entries_immutable',
                            'secret_access_audits_immutable',
                            'farm_event_inbox_immutable',
                            'ai_lab_funnel_events_immutable'
                        )
                        """
                    )
                )
            ).scalar_one()

        assert migration_count == 24
        assert constraint_count == 3
        assert retention_index_count == 1
        assert farm_outbox_column_count == 2
        assert farm_outbox_index_is_leased is True
        assert payment_reconciliation_table_count == 1
        assert payment_reconciliation_index_count == 1
        assert refund_dispatch_table_count == 1
        assert refund_dispatch_index_count == 1
        assert refund_tenant_constraint_count == 1
        assert checkout_intent_column_count == 3
        assert checkout_intent_constraint_count == 1
        assert reconciliation_lookup_column_count == 1
        assert funnel_table_count == 1
        assert funnel_index_count == 1
        assert trigger_count == 11

        await _seed_race_fixture(factory)
        start_gate = asyncio.Event()
        ready_a = asyncio.Event()
        ready_b = asyncio.Event()
        attempts = [
            asyncio.create_task(
                _race_reservation(
                    factory,
                    reservation_id="reservation-adl-pg-race-a",
                    lane_id=LANES[0],
                    start_gate=start_gate,
                    ready=ready_a,
                )
            ),
            asyncio.create_task(
                _race_reservation(
                    factory,
                    reservation_id="reservation-adl-pg-race-b",
                    lane_id=LANES[1],
                    start_gate=start_gate,
                    ready=ready_b,
                )
            ),
        ]
        await asyncio.gather(ready_a.wait(), ready_b.wait())
        start_gate.set()
        outcomes = await asyncio.gather(*attempts)

        with tenant_context(ORG):
            async with factory() as session:
                stored = (
                    await session.execute(
                        select(func.count()).select_from(DeviceReservation)
                    )
                ).scalar_one()

        assert sorted(outcomes) == ["committed", "rejected"]
        assert stored == 1
        assert await _invalid_interval_rejected(factory) is True
    finally:
        await engine.dispose()
